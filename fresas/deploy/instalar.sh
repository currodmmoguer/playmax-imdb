#!/usr/bin/env bash
# Instala Fresas como servicio en la Raspberry Pi (o cualquier Linux con
# systemd). Ejecútalo desde la carpeta fresas:  bash deploy/instalar.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="$(id -un)"
PORT="${PORT:-5001}"

echo "==> Entorno de Python en $APP_DIR/venv"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> Servicio systemd «fresas» (solo escucha en 127.0.0.1:$PORT)"
sudo tee /etc/systemd/system/fresas.service >/dev/null <<UNIT
[Unit]
Description=Fresas - gestion de campana
After=network.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=FRESAS_HTTPS=1
Environment=FRESAS_PROXY=1
ExecStart=$APP_DIR/venv/bin/waitress-serve --host 127.0.0.1 --port $PORT server:app
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=$APP_DIR/data

[Install]
WantedBy=multi-user.target
UNIT

mkdir -p "$APP_DIR/data"
chmod 700 "$APP_DIR/data"

if ! "$APP_DIR/venv/bin/python" - "$APP_DIR" <<'PY'
import sqlite3, sys, os
db = os.path.join(sys.argv[1], "data", "fresas.db")
ok = os.path.exists(db) and sqlite3.connect(db).execute(
    "SELECT name FROM sqlite_master WHERE name='usuarios'").fetchone() and \
    sqlite3.connect(db).execute("SELECT 1 FROM usuarios WHERE rol='admin' AND activo=1").fetchone()
sys.exit(0 if ok else 1)
PY
then
  echo "==> Crea el primer administrador"
  read -rp "Nombre de usuario: " ADMIN
  (cd "$APP_DIR" && ./venv/bin/python server.py crear-admin "$ADMIN")
fi

sudo systemctl daemon-reload
sudo systemctl enable --now fresas
sudo systemctl restart fresas
sleep 1
systemctl --no-pager --lines=0 status fresas || true

cat <<MSG

Listo: la app corre en http://127.0.0.1:$PORT (solo desde la propia Raspberry).
Para abrirla desde cualquier sitio con HTTPS, publícala con Tailscale Funnel:

  curl -fsSL https://tailscale.com/install.sh | sh
  sudo tailscale up
  sudo tailscale funnel --bg $PORT

La última orden te da la dirección https://<raspberry>.<tu-red>.ts.net
(ver README.md, sección «Desplegar»).
MSG
