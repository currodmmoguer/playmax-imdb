"""Playmax vs IMDB — comparador de valoraciones.

Backend Flask que actúa de proxy sobre la API de Playmax (la apiKey nunca
llega al navegador) y cruza cada ficha con el dataset oficial de IMDb
(title.ratings.tsv.gz) cargado en SQLite local.
"""

import collections
import gzip
import io
import os
import re
import sqlite3
import threading
import time
import urllib.request

import requests
from flask import Flask, jsonify, request, send_from_directory
from openpyxl import Workbook

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
IMDB_DB = os.path.join(DATA_DIR, "imdb.db")
IMDB_RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"

PLAYMAX_BASE = "https://playmax.mx/api/json/get/{page}/{version}/{key}/"
IMDB_TT_RE = re.compile(r"tt\d+")


def load_env():
    path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


load_env()
API_KEY = os.environ.get("PLAYMAX_API_KEY", "")
AUTH_KEY_FILE = os.path.join(DATA_DIR, "auth_key.txt")


def load_auth_key():
    if os.path.exists(AUTH_KEY_FILE):
        with open(AUTH_KEY_FILE) as f:
            return f.read().strip()
    return ""


def save_auth_key(key):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(AUTH_KEY_FILE, "w") as f:
        f.write(key)


AUTH_KEY = load_auth_key()

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# ---------------------------------------------------------------------------
# Cliente Playmax
# ---------------------------------------------------------------------------

# La API limita a 20 peticiones cada 10 segundos por IP; cacheamos las
# respuestas de fichas para no agotar el límite al comparar listados.
_ficha_cache = {}
_FICHA_CACHE_TTL = 3600


# Limitador global: la API permite 20 peticiones cada 10 segundos por IP;
# nos quedamos en 18 para dejar margen.
_pm_calls = collections.deque()
_pm_lock = threading.Lock()


def _throttle():
    while True:
        with _pm_lock:
            now = time.time()
            while _pm_calls and now - _pm_calls[0] > 10:
                _pm_calls.popleft()
            if len(_pm_calls) < 18:
                _pm_calls.append(now)
                return
            wait = 10 - (now - _pm_calls[0]) + 0.05
        time.sleep(wait)


def playmax_get(page, params=None, version="v1"):
    _throttle()
    url = PLAYMAX_BASE.format(page=page, version=version, key=API_KEY)
    if AUTH_KEY:
        url += AUTH_KEY + "/"
    r = requests.get(url, params=params or {}, timeout=20)
    data = r.json()
    err = data.get("error", {})
    if err.get("code", 0) != 0:
        raise PlaymaxError(err.get("code"), err.get("message", "unknown"),
                           err.get("httpCode", 500))
    return data


class PlaymaxError(Exception):
    def __init__(self, code, message, http_code):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_code = http_code


def get_ficha(ficha_id):
    now = time.time()
    cached = _ficha_cache.get(ficha_id)
    if cached and now - cached[0] < _FICHA_CACHE_TTL:
        return cached[1]
    data = playmax_get("ficha", {"fichaId": ficha_id})
    _ficha_cache[ficha_id] = (now, data)
    return data


def extract_imdb_id(ficha_info):
    for link in ficha_info.get("externalLinks") or []:
        if str(link.get("name", "")).lower() == "imdb":
            ext = str(link.get("externalId", ""))
            m = IMDB_TT_RE.search(ext) or IMDB_TT_RE.search(str(link.get("link", "")))
            if m:
                return m.group(0)
    return None


# ---------------------------------------------------------------------------
# Dataset de valoraciones de IMDb
# ---------------------------------------------------------------------------

_imdb_state = {"status": "missing", "rows": 0, "updated": None, "error": None}
_imdb_lock = threading.Lock()


def _db():
    conn = sqlite3.connect(IMDB_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS ratings (
        tconst TEXT PRIMARY KEY, rating REAL, votes INTEGER)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY, value TEXT)""")
    # Mapeo persistente ficha de Playmax -> título de IMDb. tconst vacío
    # significa "consultada y sin enlace a IMDb" (evita re-consultarla).
    conn.execute("""CREATE TABLE IF NOT EXISTS ficha_imdb (
        fichaId INTEGER PRIMARY KEY, tconst TEXT, updated INTEGER)""")
    return conn


def _refresh_imdb_state():
    if not os.path.exists(IMDB_DB):
        return
    conn = _db()
    try:
        rows = conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0]
        updated = conn.execute(
            "SELECT value FROM meta WHERE key='updated'").fetchone()
        if rows:
            _imdb_state.update(status="ready", rows=rows,
                               updated=updated[0] if updated else None)
    finally:
        conn.close()


def download_imdb_dataset():
    with _imdb_lock:
        if _imdb_state["status"] == "loading":
            return
        _imdb_state.update(status="loading", error=None)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        req = urllib.request.Request(
            IMDB_RATINGS_URL, headers={"User-Agent": "playmax-imdb/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
        conn = _db()
        try:
            def rows():
                with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8") as f:
                    next(f)  # cabecera: tconst averageRating numVotes
                    for line in f:
                        t, r, v = line.rstrip("\n").split("\t")
                        yield t, float(r), int(v)

            # se construye en una tabla nueva y se intercambia al final para
            # que las consultas sigan funcionando durante la recarga
            conn.execute("DROP TABLE IF EXISTS ratings_new")
            conn.execute("""CREATE TABLE ratings_new (
                tconst TEXT PRIMARY KEY, rating REAL, votes INTEGER)""")
            conn.executemany("INSERT INTO ratings_new VALUES (?,?,?)", rows())
            conn.execute(
                "INSERT OR REPLACE INTO meta VALUES ('updated', ?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"),))
            conn.commit()
            conn.execute("DROP TABLE ratings")
            conn.execute("ALTER TABLE ratings_new RENAME TO ratings")
            conn.commit()
        finally:
            conn.close()
        _refresh_imdb_state()
    except Exception as e:  # noqa: BLE001 - se reporta al frontend
        _imdb_state.update(status="error", error=str(e))


IMDB_MAX_AGE = 24 * 3600


def imdb_auto_refresh():
    """Comprueba cada hora la antigüedad del dataset de IMDb y lo vuelve a
    descargar cuando supera las 24 horas (IMDb lo publica a diario)."""
    while True:
        try:
            if _imdb_state["status"] == "ready" and _imdb_state["updated"]:
                age = time.time() - time.mktime(
                    time.strptime(_imdb_state["updated"], "%Y-%m-%d %H:%M:%S"))
                if age > IMDB_MAX_AGE:
                    download_imdb_dataset()
        except Exception:  # noqa: BLE001 - tarea de fondo
            import traceback
            traceback.print_exc()
        time.sleep(3600)


def imdb_rating(tconst):
    # no exigimos status "ready": durante una recarga del dataset la tabla
    # antigua sigue siendo válida y consultable
    if not tconst or not os.path.exists(IMDB_DB):
        return None
    conn = sqlite3.connect(IMDB_DB)
    try:
        row = conn.execute(
            "SELECT rating, votes FROM ratings WHERE tconst=?",
            (tconst,)).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    if not row:
        return None
    return {"rating": row[0], "votes": row[1]}


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

@app.errorhandler(PlaymaxError)
def handle_playmax_error(e):
    return jsonify({"error": f"Playmax: {e.message}", "code": e.code}), e.http_code


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/status")
def status():
    playmax = {"ok": False, "message": "", "needsAuth": False}
    try:
        playmax_get("popular_fichas", {"limit": 1})
        playmax["ok"] = True
    except PlaymaxError as e:
        playmax["message"] = e.message
        # code 3 = user not login, 33 = auth key not found (caducada/revocada)
        playmax["needsAuth"] = e.code in (3, 33)
    except requests.RequestException as e:
        playmax["message"] = str(e)
    return jsonify({"playmax": playmax, "imdb": _imdb_state})


@app.route("/api/auth/start", methods=["POST"])
def auth_start():
    """Solicita una authKey nueva y devuelve la URL que el usuario debe
    visitar para autorizar la app. La authKey caduca en 1 hora si no se
    autoriza; una vez autorizada queda activa para siempre."""
    global AUTH_KEY
    url = PLAYMAX_BASE.format(page="user_authorization", version="v1", key=API_KEY)
    r = requests.get(url, timeout=20)
    data = r.json()
    err = data.get("error", {})
    if err.get("code", 0) != 0:
        raise PlaymaxError(err.get("code"), err.get("message", "unknown"),
                           err.get("httpCode", 500))
    result = data.get("result", {})
    AUTH_KEY = result.get("authKey", "")
    save_auth_key(AUTH_KEY)
    return jsonify({"authUrl": result.get("authUrl")})


@app.route("/api/imdb/update", methods=["POST"])
def imdb_update():
    threading.Thread(target=download_imdb_dataset, daemon=True).start()
    return jsonify({"started": True})


@app.route("/api/search")
def search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify({"error": "La búsqueda necesita al menos 2 caracteres"}), 400
    data = playmax_get("search", {"query": q, "sections[]": 1}, version="v1.1")
    fichas = (data.get("result", {}).get("ficha") or {}).get("fichas", [])
    return jsonify({"fichas": fichas})


@app.route("/api/explore")
def explore():
    params = {
        "order": request.args.get("order", "9"),  # 9 = más populares
        "direction": 0,
        "limit": int(request.args.get("limit", 24)),
        "start": int(request.args.get("start", 0)),
    }
    ficha_type = request.args.get("type")
    if ficha_type in ("1", "2", "3"):
        params["fichaType[]"] = ficha_type
    data = playmax_get("explore", params)
    return jsonify({
        "fichas": data.get("result", {}).get("fichas", []),
        "pagination": data.get("pagination", {}),
    })


@app.route("/api/explore_imdb")
def explore_imdb():
    """Obtiene los mejores valorados de IMDb (ordenados por IMDb) con datos de Playmax."""
    if not os.path.exists(IMDB_DB):
        return jsonify({"fichas": [], "pagination": {}})

    limit = int(request.args.get("limit", 24))
    start = int(request.args.get("start", 0))
    ficha_type = request.args.get("type")  # 1=Series, 2=Películas, 3=Documentales

    conn = sqlite3.connect(IMDB_DB)
    try:
        # Obtener tconsts ordenados por rating de IMDb que existan en Playmax
        # Buscamos más para compensar los que fallan al traer de Playmax o no coinciden con el filtro
        rows = conn.execute("""
            SELECT r.tconst, r.rating, r.votes, f.fichaId
            FROM ratings r
            INNER JOIN ficha_imdb f ON f.tconst = r.tconst
            WHERE r.votes > 100 AND f.tconst != ''
            ORDER BY r.rating DESC, r.votes DESC
            LIMIT ? OFFSET ?
        """, (limit * 3 + 20, start)).fetchall()

        fichas = []
        for tconst, rating, votes, ficha_id in rows:
            if len(fichas) >= limit:
                break
            try:
                # Obtener información de Playmax
                pm_data = get_ficha(ficha_id).get("result", {}).get("info", {})
                pm_type = pm_data.get("type", "")

                # Mapeo de tipos para el filtro
                type_map = {
                    "Serie": "1",
                    "Miniserie": "1",
                    "Película": "2",
                    "Documental": "3",
                    "Serie de animación": "1",
                }
                pm_type_code = type_map.get(pm_type, "")

                # Aplicar filtro de tipo si se especifica
                if ficha_type and pm_type_code != ficha_type:
                    continue

                fichas.append({
                    "id": ficha_id,
                    "title": pm_data.get("title", f"[{ficha_id}]"),
                    "type": pm_type,
                    "year": pm_data.get("year"),
                    "poster": pm_data.get("poster"),
                    "rating": pm_data.get("rating"),
                    "votes": pm_data.get("votes"),
                    "imdbId": tconst,
                    "imdbRating": rating,
                    "imdbVotes": votes,
                })
            except Exception:
                # Si falla traer de Playmax, saltar
                pass

        # Calcular si hay más resultados
        # Para el siguiente inicio, añadir el límite
        next_start = start + limit if len(fichas) >= limit else None

        return jsonify({
            "fichas": fichas[:limit],
            "pagination": {"next": next_start} if next_start else {},
        })
    finally:
        conn.close()


_bg_resolving = threading.Lock()


def background_resolve_all():
    """Recorre my_fichas y resuelve los imdbId pendientes al ritmo que
    permite el límite de la API. Se lanza al arrancar el servidor para que
    el mapeo se complete aunque no haya ningún navegador abierto."""
    if not _bg_resolving.acquire(blocking=False):
        return
    try:
        data = playmax_get("my_fichas", version="v1.1")
        ids = set()
        for states in data.get("result", {}).get("sections", {}).values():
            for fichas in states.values():
                ids.update(f["id"] for f in fichas)
        conn = sqlite3.connect(IMDB_DB)
        try:
            known = {r[0] for r in conn.execute(
                "SELECT fichaId FROM ficha_imdb").fetchall()}
            for fid in sorted(ids - known):
                info = get_ficha(fid).get("result", {}).get("info", {})
                conn.execute(
                    "INSERT OR REPLACE INTO ficha_imdb VALUES (?,?,?)",
                    (fid, extract_imdb_id(info) or "", int(time.time())))
                conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - tarea de fondo, mejor log que crash
        import traceback
        traceback.print_exc()
    finally:
        _bg_resolving.release()


@app.route("/api/my_fichas")
def my_fichas():
    data = playmax_get("my_fichas", version="v1.1")
    sections = data.get("result", {}).get("sections", {})

    rows = {}
    for group, states in sections.items():
        for state, fichas in states.items():
            for f in fichas:
                fid = f["id"]
                # una ficha puede salir en "episode.pending" y en su sección
                # de series; preferimos la entrada de la sección principal
                if fid in rows and group == "episode":
                    continue
                user = f.get("user") or {}
                rows[fid] = {
                    "id": fid,
                    "title": f.get("title"),
                    "poster": f.get("poster"),
                    "type": f.get("type"),
                    "year": f.get("year"),
                    "group": "series" if group == "episode" else group,
                    "marked": user.get("marked"),
                    "myRating": user.get("rating") or None,
                    "playmax": {"rating": f.get("rating"), "votes": f.get("votes")},
                    "imdbId": None,
                    "imdb": None,
                    "resolved": False,
                    "status": None,
                }

    if rows:
        conn = sqlite3.connect(IMDB_DB)
        try:
            qmarks = ",".join("?" * len(rows))
            for fid, tconst, rating, votes in conn.execute(
                    f"""SELECT m.fichaId, m.tconst, r.rating, r.votes
                        FROM ficha_imdb m LEFT JOIN ratings r ON r.tconst = m.tconst
                        WHERE m.fichaId IN ({qmarks})""", list(rows)):
                row = rows[fid]
                row["resolved"] = True
                row["imdbId"] = tconst or None
                if rating is not None:
                    row["imdb"] = {"rating": rating, "votes": votes}
        finally:
            conn.close()

    return jsonify({"fichas": list(rows.values())})


@app.route("/api/imdb/resolve", methods=["POST"])
def imdb_resolve():
    """Resuelve el imdbId de hasta 15 fichas consultando su detalle en
    Playmax (limitado por _throttle) y persiste el mapeo."""
    ids = (request.get_json(silent=True) or {}).get("ids", [])[:15]
    out = {}
    conn = sqlite3.connect(IMDB_DB)
    try:
        for fid in ids:
            fid = int(fid)
            try:
                data = get_ficha(fid)
            except (PlaymaxError, requests.RequestException) as e:
                out[fid] = {"error": str(e)}
                continue
            info = data.get("result", {}).get("info", {})
            tconst = extract_imdb_id(info) or ""
            conn.execute("INSERT OR REPLACE INTO ficha_imdb VALUES (?,?,?)",
                         (fid, tconst, int(time.time())))
            out[fid] = {"imdbId": tconst or None,
                        "imdb": imdb_rating(tconst) if tconst else None}
        conn.commit()
    finally:
        conn.close()
    return jsonify(out)


@app.route("/api/ficha/<int:ficha_id>")
def ficha(ficha_id):
    data = get_ficha(ficha_id)
    info = data.get("result", {}).get("info", {})
    tconst = extract_imdb_id(info)
    conn = sqlite3.connect(IMDB_DB)
    try:
        conn.execute("INSERT OR REPLACE INTO ficha_imdb VALUES (?,?,?)",
                     (ficha_id, tconst or "", int(time.time())))
        conn.commit()
    finally:
        conn.close()
    imdb = imdb_rating(tconst)

    playmax_rating = info.get("rating")
    comparison = None
    if imdb and playmax_rating is not None:
        comparison = round(float(playmax_rating) - imdb["rating"], 2)

    return jsonify({
        "id": ficha_id,
        "title": info.get("title"),
        "originalTitle": info.get("originalTitle"),
        "year": info.get("year"),
        "type": info.get("type"),
        "poster": info.get("poster"),
        "cover": info.get("cover"),
        "sinopsis": data.get("result", {}).get("sinopsis"),
        "playmax": {"rating": playmax_rating, "votes": info.get("votes")},
        "imdbId": tconst,
        "imdbUrl": f"https://www.imdb.com/title/{tconst}/" if tconst else None,
        "imdb": imdb,
        "imdbDbStatus": _imdb_state["status"],
        "difference": comparison,
        "status": info.get("status") if info.get("type") == "Serie" else None,
    })


@app.route("/api/series-status", methods=["POST"])
def series_status():
    """Obtiene el status de varias series. Recibe: {"ids": [1,2,3,...]}"""
    # Mapeo de valores de Playmax a valores esperados por el frontend
    STATUS_MAP = {
        "finalized": "finished",
        "emission": "in production",
        "waiting for new season": "waiting for new season",
        "cancelled": "cancelled",
    }
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    out = {}
    for fid in ids:
        try:
            fid_int = int(fid)
            data = get_ficha(fid_int)
            info = data.get("result", {}).get("info", {})
            status = info.get("status")
            ficha_type = info.get("type")
            # Mapear el status a valores del frontend
            if ficha_type == "Serie" and status:
                out[str(fid_int)] = STATUS_MAP.get(status, status)
        except PlaymaxError:
            pass
        except Exception:
            pass
    return jsonify(out)


@app.route("/api/my_fichas_status", methods=["POST"])
def my_fichas_status():
    """Obtiene status de series del usuario en lotes, respetando throttle de API."""
    STATUS_MAP = {
        "finalized": "finished",
        "emission": "in production",
        "waiting for new season": "waiting for new season",
        "cancelled": "cancelled",
    }
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    out = {}
    # Procesar en lotes pequeños (máximo 5 series por lote)
    # para no tardar demasiado: 5 series × 0.3s/serie ≈ 1.5s por lote
    for i in range(0, len(ids), 5):
        batch = ids[i:i+5]
        for fid in batch:
            try:
                fid_int = int(fid)
                data = get_ficha(fid_int)
                info = data.get("result", {}).get("info", {})
                status = info.get("status")
                ficha_type = info.get("type")
                if ficha_type == "Serie" and status:
                    out[str(fid_int)] = STATUS_MAP.get(status, status)
            except Exception:
                pass
    return jsonify(out)


@app.route("/api/export/fichas", methods=["POST"])
def export_fichas():
    data = request.get_json(silent=True) or {}
    fichas = data.get("fichas", [])
    if not fichas:
        return {"error": "No hay fichas para exportar"}, 400

    wb = Workbook()
    ws = wb.active
    ws.title = "Fichas"

    headers = ["Título", "Año", "Tipo", "Estado", "Estado serie", "Mi nota",
               "Playmax (rating)", "Playmax (votos)",
               "IMDb (rating)", "IMDb (votos)", "Diferencia"]
    ws.append(headers)
    ws.freeze_panes = "A2"

    mark_labels = {
        "following": "Siguiendo", "pending": "Pendiente", "favorite": "Favorita",
        "viewed": "Vista", "abandoned": "Abandonada",
    }
    status_labels = {
        "finished": "Finalizada",
        "waiting for new season": "Esperando temporada",
        "in production": "En producción",
        "cancelled": "Cancelada",
    }

    for f in fichas:
        pm_rating = f.get("playmax", {}).get("rating")
        pm_votes = f.get("playmax", {}).get("votes")
        imdb_rating = f.get("imdb", {}).get("rating") if f.get("imdb") else None
        imdb_votes = f.get("imdb", {}).get("votes") if f.get("imdb") else None
        status = f.get("status")

        diff = None
        if pm_rating is not None and imdb_rating is not None:
            diff = round(pm_rating - imdb_rating, 2)

        ws.append([
            f.get("title", ""),
            f.get("year") or "",
            f.get("type", ""),
            mark_labels.get(f.get("marked"), f.get("marked", "")),
            status_labels.get(status, status or ""),
            f.get("myRating") or "",
            pm_rating or "",
            pm_votes or "",
            imdb_rating or "",
            imdb_votes or "",
            diff or "",
        ])

    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 14
    for col in "FGHI":
        ws.column_dimensions[col].width = 12

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return app.response_class(
        output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=fichas.xlsx"}
    )


if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    _db().close()  # asegura el esquema (tabla ficha_imdb incluida)
    _refresh_imdb_state()
    if _imdb_state["status"] == "missing":
        threading.Thread(target=download_imdb_dataset, daemon=True).start()
    if AUTH_KEY:
        threading.Thread(target=background_resolve_all, daemon=True).start()
    threading.Thread(target=imdb_auto_refresh, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
