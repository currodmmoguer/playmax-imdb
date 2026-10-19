"""Fresas — gestión de una explotación de fresa al estilo de Huelva.

Backend Flask + SQLite para llevar la campaña: fincas y sectores
(macrotúneles), trabajadores, recolección diaria, entregas a la cooperativa
y el cuaderno de campo de tratamientos fitosanitarios (con control del plazo
de seguridad antes de recolectar).
"""

import datetime
import io
import os
import sqlite3

from flask import Flask, g, jsonify, request, send_file, send_from_directory
from openpyxl import Workbook

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get("FRESAS_DB", os.path.join(DATA_DIR, "fresas.db"))

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

CATEGORIAS = ["Extra", "Primera", "Segunda", "Industria"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS fincas (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    municipio TEXT,
    notas TEXT
);
CREATE TABLE IF NOT EXISTS sectores (
    id INTEGER PRIMARY KEY,
    finca_id INTEGER NOT NULL REFERENCES fincas(id),
    nombre TEXT NOT NULL,
    variedad TEXT,
    superficie_ha REAL,
    plantas INTEGER,
    fecha_plantacion TEXT
);
CREATE TABLE IF NOT EXISTS trabajadores (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    dni TEXT,
    telefono TEXT,
    cuadrilla TEXT,
    fecha_alta TEXT,
    activo INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS recolecciones (
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL,
    sector_id INTEGER NOT NULL REFERENCES sectores(id),
    trabajador_id INTEGER REFERENCES trabajadores(id),
    categoria TEXT NOT NULL,
    cajas INTEGER,
    kg REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS entregas (
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL,
    destino TEXT NOT NULL,
    albaran TEXT,
    categoria TEXT NOT NULL,
    kg REAL NOT NULL,
    precio_kg REAL
);
CREATE TABLE IF NOT EXISTS tratamientos (
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL,
    sector_id INTEGER NOT NULL REFERENCES sectores(id),
    producto TEXT NOT NULL,
    num_registro TEXT,
    materia_activa TEXT,
    plaga TEXT,
    dosis TEXT,
    plazo_seguridad_dias INTEGER NOT NULL DEFAULT 0,
    aplicador TEXT
);
CREATE INDEX IF NOT EXISTS idx_recol_fecha ON recolecciones(fecha);
CREATE INDEX IF NOT EXISTS idx_entregas_fecha ON entregas(fecha);
CREATE INDEX IF NOT EXISTS idx_trat_sector ON tratamientos(sector_id, fecha);
"""

# Definición de las tablas editables desde la API genérica: campo -> tipo.
TABLES = {
    "fincas": {
        "fields": {"nombre": "str", "municipio": "str", "notas": "str"},
        "required": ["nombre"],
        "order": "nombre",
    },
    "sectores": {
        "fields": {"finca_id": "int", "nombre": "str", "variedad": "str",
                   "superficie_ha": "float", "plantas": "int",
                   "fecha_plantacion": "date"},
        "required": ["finca_id", "nombre"],
        "order": "finca_id, nombre",
    },
    "trabajadores": {
        "fields": {"nombre": "str", "dni": "str", "telefono": "str",
                   "cuadrilla": "str", "fecha_alta": "date", "activo": "bool"},
        "required": ["nombre"],
        "order": "activo DESC, nombre",
    },
    "recolecciones": {
        "fields": {"fecha": "date", "sector_id": "int", "trabajador_id": "int",
                   "categoria": "categoria", "cajas": "int", "kg": "float"},
        "required": ["fecha", "sector_id", "categoria", "kg"],
        "order": "fecha DESC, id DESC",
        "campana": True,
    },
    "entregas": {
        "fields": {"fecha": "date", "destino": "str", "albaran": "str",
                   "categoria": "categoria", "kg": "float", "precio_kg": "float"},
        "required": ["fecha", "destino", "categoria", "kg"],
        "order": "fecha DESC, id DESC",
        "campana": True,
    },
    "tratamientos": {
        "fields": {"fecha": "date", "sector_id": "int", "producto": "str",
                   "num_registro": "str", "materia_activa": "str",
                   "plaga": "str", "dosis": "str",
                   "plazo_seguridad_dias": "int", "aplicador": "str"},
        "required": ["fecha", "sector_id", "producto"],
        "order": "fecha DESC, id DESC",
        "campana": True,
    },
}


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

def campana_de(fecha):
    """Campaña de una fecha ISO. En Huelva se planta en octubre y se recoge
    hasta junio, así que la campaña va de septiembre a agosto: 2026/27."""
    if not fecha:
        return None
    y, m = int(fecha[:4]), int(fecha[5:7])
    if m < 9:
        y -= 1
    return f"{y}/{(y + 1) % 100:02d}"


def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.create_function("campana", 1, campana_de, deterministic=True)
        g.db = db
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        get_db().executescript(SCHEMA)


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


class ValidationError(Exception):
    pass


def parse_payload(table, data):
    spec = TABLES[table]
    out = {}
    for name, kind in spec["fields"].items():
        if name not in data:
            continue
        v = data[name]
        if v in ("", None):
            out[name] = None
            continue
        try:
            if kind == "int":
                v = int(v)
            elif kind == "float":
                v = float(str(v).replace(",", "."))
            elif kind == "bool":
                v = 1 if v in (True, 1, "1", "true", "on") else 0
            elif kind == "date":
                v = datetime.date.fromisoformat(str(v)).isoformat()
            elif kind == "categoria":
                if v not in CATEGORIAS:
                    raise ValueError
            else:
                v = str(v).strip()
        except ValueError:
            raise ValidationError(f"Valor no válido en «{name}»")
        if kind in ("int", "float") and v < 0:
            raise ValidationError(f"«{name}» no puede ser negativo")
        out[name] = v
    return out


def check_required(table, values):
    missing = [f for f in TABLES[table]["required"] if values.get(f) is None]
    if missing:
        raise ValidationError("Faltan campos: " + ", ".join(missing))


def tratamientos_activos(db, sector_id, fecha):
    """Tratamientos cuyo plazo de seguridad todavía no ha vencido en `fecha`."""
    return rows(db.execute(
        """SELECT t.*, date(t.fecha, '+' || t.plazo_seguridad_dias || ' days')
                  AS recolectable_desde
           FROM tratamientos t
           WHERE t.sector_id = ? AND t.fecha <= ?
             AND date(t.fecha, '+' || t.plazo_seguridad_dias || ' days') > ?
           ORDER BY recolectable_desde DESC""",
        (sector_id, fecha, fecha)))


# ---------------------------------------------------------------------------
# API genérica (CRUD)
# ---------------------------------------------------------------------------

@app.errorhandler(ValidationError)
def on_validation_error(e):
    return jsonify(error=str(e)), 400


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/meta")
def meta():
    db = get_db()
    campanas = {campana_de(datetime.date.today().isoformat())}
    for t in ("recolecciones", "entregas", "tratamientos"):
        for r in db.execute(f"SELECT DISTINCT campana(fecha) c FROM {t}"):
            campanas.add(r["c"])
    return jsonify(categorias=CATEGORIAS,
                   campanas=sorted(campanas, reverse=True),
                   campana_actual=campana_de(datetime.date.today().isoformat()))


@app.route("/api/<table>", methods=["GET"])
def list_rows(table):
    if table not in TABLES:
        return jsonify(error="No existe"), 404
    spec = TABLES[table]
    sql, args = f"SELECT * FROM {table}", []
    camp = request.args.get("campana")
    if camp and spec.get("campana"):
        sql += " WHERE campana(fecha) = ?"
        args.append(camp)
    sql += f" ORDER BY {spec['order']}"
    return jsonify(rows(get_db().execute(sql, args)))


@app.route("/api/<table>", methods=["POST"])
def create_row(table):
    if table not in TABLES:
        return jsonify(error="No existe"), 404
    data = request.get_json(force=True) or {}
    values = parse_payload(table, data)
    check_required(table, values)
    db = get_db()
    if table == "recolecciones" and not data.get("forzar"):
        activos = tratamientos_activos(db, values["sector_id"], values["fecha"])
        if activos:
            t = activos[0]
            return jsonify(
                error=(f"Plazo de seguridad en vigor: «{t['producto']}» aplicado "
                       f"el {t['fecha']}, no se puede recolectar hasta el "
                       f"{t['recolectable_desde']}."),
                plazo_seguridad=activos), 409
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    try:
        cur = db.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})",
                         list(values.values()))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify(error="Referencia no válida"), 400
    return jsonify(dict(db.execute(f"SELECT * FROM {table} WHERE id = ?",
                                   (cur.lastrowid,)).fetchone())), 201


@app.route("/api/<table>/<int:row_id>", methods=["PUT"])
def update_row(table, row_id):
    if table not in TABLES:
        return jsonify(error="No existe"), 404
    db = get_db()
    current = db.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if current is None:
        return jsonify(error="No existe"), 404
    values = parse_payload(table, request.get_json(force=True) or {})
    check_required(table, {**dict(current), **values})
    if values:
        sets = ", ".join(f"{c} = ?" for c in values)
        try:
            db.execute(f"UPDATE {table} SET {sets} WHERE id = ?",
                       [*values.values(), row_id])
            db.commit()
        except sqlite3.IntegrityError:
            return jsonify(error="Referencia no válida"), 400
    return jsonify(dict(db.execute(f"SELECT * FROM {table} WHERE id = ?",
                                   (row_id,)).fetchone()))


@app.route("/api/<table>/<int:row_id>", methods=["DELETE"])
def delete_row(table, row_id):
    if table not in TABLES:
        return jsonify(error="No existe"), 404
    db = get_db()
    try:
        db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify(error="No se puede borrar: tiene registros asociados"), 409
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Resumen de campaña y plazos de seguridad
# ---------------------------------------------------------------------------

@app.route("/api/plazos")
def plazos():
    """Sectores con plazo de seguridad en vigor en la fecha dada (hoy)."""
    fecha = request.args.get("fecha") or datetime.date.today().isoformat()
    db = get_db()
    out = []
    for s in db.execute("SELECT id FROM sectores"):
        activos = tratamientos_activos(db, s["id"], fecha)
        if activos:
            out.append({"sector_id": s["id"], "tratamientos": activos,
                        "recolectable_desde": activos[0]["recolectable_desde"]})
    return jsonify(out)


@app.route("/api/resumen")
def resumen():
    db = get_db()
    camp = request.args.get("campana") or campana_de(datetime.date.today().isoformat())
    w = "campana(fecha) = ?"

    total = db.execute(
        f"SELECT COALESCE(SUM(kg), 0) kg, COALESCE(SUM(cajas), 0) cajas, "
        f"COUNT(DISTINCT fecha) dias FROM recolecciones WHERE {w}",
        (camp,)).fetchone()
    por_categoria = rows(db.execute(
        f"SELECT categoria, SUM(kg) kg FROM recolecciones WHERE {w} "
        f"GROUP BY categoria", (camp,)))
    # Semana empezando en lunes (strftime %w: 0 = domingo).
    por_semana = rows(db.execute(
        f"""SELECT date(fecha, '-' || ((CAST(strftime('%w', fecha) AS INTEGER) + 6) % 7)
                        || ' days') semana,
                   SUM(kg) kg
            FROM recolecciones WHERE {w} GROUP BY semana ORDER BY semana""",
        (camp,)))
    por_sector = rows(db.execute(
        f"""SELECT s.id sector_id, s.nombre sector, f.nombre finca, s.variedad,
                   s.superficie_ha, s.plantas, COALESCE(SUM(r.kg), 0) kg
            FROM sectores s JOIN fincas f ON f.id = s.finca_id
            LEFT JOIN recolecciones r ON r.sector_id = s.id AND campana(r.fecha) = ?
            GROUP BY s.id ORDER BY kg DESC""", (camp,)))
    for s in por_sector:
        s["kg_ha"] = s["kg"] / s["superficie_ha"] if s["superficie_ha"] else None
        s["g_planta"] = s["kg"] * 1000 / s["plantas"] if s["plantas"] else None
    por_trabajador = rows(db.execute(
        f"""SELECT t.id trabajador_id, t.nombre, t.cuadrilla,
                   SUM(r.kg) kg, SUM(r.cajas) cajas, COUNT(DISTINCT r.fecha) dias
            FROM recolecciones r JOIN trabajadores t ON t.id = r.trabajador_id
            WHERE campana(r.fecha) = ?
            GROUP BY t.id ORDER BY kg DESC""", (camp,)))
    for t in por_trabajador:
        t["kg_dia"] = t["kg"] / t["dias"] if t["dias"] else None
    ent = db.execute(
        f"SELECT COALESCE(SUM(kg), 0) kg, COALESCE(SUM(kg * precio_kg), 0) importe, "
        f"SUM(CASE WHEN precio_kg IS NOT NULL THEN kg END) kg_liquidados "
        f"FROM entregas WHERE {w}", (camp,)).fetchone()
    ent_cat = rows(db.execute(
        f"""SELECT categoria, SUM(kg) kg, SUM(kg * precio_kg) importe,
                   SUM(kg * precio_kg) / NULLIF(SUM(CASE WHEN precio_kg IS NOT NULL
                                                    THEN kg END), 0) precio_medio
            FROM entregas WHERE {w} GROUP BY categoria""", (camp,)))

    return jsonify(
        campana=camp,
        recolectado={"kg": total["kg"], "cajas": total["cajas"], "dias": total["dias"]},
        por_categoria=por_categoria,
        por_semana=por_semana,
        por_sector=por_sector,
        por_trabajador=por_trabajador,
        entregado={"kg": ent["kg"], "importe": ent["importe"],
                   "precio_medio": (ent["importe"] / ent["kg_liquidados"]
                                    if ent["kg_liquidados"] else None),
                   "por_categoria": ent_cat},
    )


# ---------------------------------------------------------------------------
# Exportación a Excel
# ---------------------------------------------------------------------------

def xlsx_response(wb, filename):
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/export/cuaderno")
def export_cuaderno():
    """Cuaderno de campo: registro de tratamientos fitosanitarios."""
    camp = request.args.get("campana") or campana_de(datetime.date.today().isoformat())
    data = get_db().execute(
        """SELECT t.fecha, f.nombre finca, s.nombre sector, s.variedad,
                  s.superficie_ha, t.plaga, t.producto, t.num_registro,
                  t.materia_activa, t.dosis, t.plazo_seguridad_dias,
                  date(t.fecha, '+' || t.plazo_seguridad_dias || ' days'), t.aplicador
           FROM tratamientos t JOIN sectores s ON s.id = t.sector_id
           JOIN fincas f ON f.id = s.finca_id
           WHERE campana(t.fecha) = ? ORDER BY t.fecha""", (camp,)).fetchall()
    wb = Workbook()
    ws = wb.active
    ws.title = "Tratamientos"
    ws.append(["Fecha", "Finca", "Sector", "Variedad", "Superficie (ha)",
               "Plaga / problema", "Producto", "Nº registro", "Materia activa",
               "Dosis", "Plazo seguridad (días)", "Recolectable desde",
               "Aplicador"])
    for r in data:
        ws.append(list(r))
    return xlsx_response(wb, f"cuaderno-campo-{camp.replace('/', '-')}.xlsx")


@app.route("/api/export/campana")
def export_campana():
    """Recolección y entregas de la campaña, una hoja por tipo."""
    camp = request.args.get("campana") or campana_de(datetime.date.today().isoformat())
    db = get_db()
    wb = Workbook()
    ws = wb.active
    ws.title = "Recolección"
    ws.append(["Fecha", "Finca", "Sector", "Variedad", "Trabajador",
               "Cuadrilla", "Categoría", "Cajas", "Kg"])
    for r in db.execute(
            """SELECT r.fecha, f.nombre, s.nombre, s.variedad, t.nombre,
                      t.cuadrilla, r.categoria, r.cajas, r.kg
               FROM recolecciones r JOIN sectores s ON s.id = r.sector_id
               JOIN fincas f ON f.id = s.finca_id
               LEFT JOIN trabajadores t ON t.id = r.trabajador_id
               WHERE campana(r.fecha) = ? ORDER BY r.fecha""", (camp,)):
        ws.append(list(r))
    ws = wb.create_sheet("Entregas")
    ws.append(["Fecha", "Destino", "Albarán", "Categoría", "Kg", "€/kg", "Importe"])
    for r in db.execute(
            """SELECT fecha, destino, albaran, categoria, kg, precio_kg,
                      kg * precio_kg FROM entregas
               WHERE campana(fecha) = ? ORDER BY fecha""", (camp,)):
        ws.append(list(r))
    return xlsx_response(wb, f"campana-{camp.replace('/', '-')}.xlsx")


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), debug=False)
