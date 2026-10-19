# 🍓 Fresas — gestión de campaña

Aplicación web para llevar una explotación de fresa tal y como se trabaja en
Huelva: fincas con sectores de macrotúnel, temporeros por cuadrillas,
recolección diaria por categorías, entregas a la cooperativa y el cuaderno de
campo de tratamientos fitosanitarios.

Es independiente del comparador Playmax/IMDb del resto del repositorio
(Flask + SQLite + HTML/JS sin dependencias), pensada para correr en la misma
Raspberry Pi y usarse desde el móvil en el campo, con usuarios y acceso
seguro (HTTPS) desde cualquier sitio.

## Desplegar en la Raspberry Pi (acceso desde cualquier sitio)

Copia el repositorio a la Raspberry y, desde la carpeta `fresas`:

```bash
bash deploy/instalar.sh
```

El script crea el entorno de Python, instala la app como servicio `fresas`
(arranca sola al encender la Raspberry) y te pide el usuario y la contraseña
del primer administrador. El servicio solo escucha en `127.0.0.1:5001`: no
se puede entrar directamente por la red, solo a través del túnel HTTPS.

### Publicarla con HTTPS: Tailscale Funnel (recomendado)

Es gratis, no hace falta comprar dominio ni abrir puertos en el router, y el
certificado HTTPS se renueva solo.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up            # abre el enlace que aparece e inicia sesión
sudo tailscale funnel --bg 5001
```

La primera vez, `tailscale funnel` te da un enlace para activar Funnel en tu
cuenta. Al terminar muestra la dirección pública, del tipo
`https://raspberrypi.tu-red.ts.net`: esa es la que abres desde el móvil, en el
campo o en casa. En el móvil puedes «Añadir a pantalla de inicio» para tenerla
como una app.

### Alternativa: Cloudflare Tunnel

Si tienes un dominio propio en Cloudflare, puedes publicarla en p. ej.
`https://fresas.tudominio.es` con un túnel de Cloudflare (Zero Trust →
Networks → Tunnels) apuntando a `http://localhost:5001`. La app funciona igual
detrás de cualquier proxy HTTPS.

### Mantenimiento

```bash
sudo systemctl status fresas         # ¿está funcionando?
sudo journalctl -u fresas -n 50      # últimos mensajes
git pull && sudo systemctl restart fresas   # actualizar
```

**Copia de seguridad:** toda la información está en `fresas/data/fresas.db`.
Cópiala con regularidad fuera de la Raspberry (p. ej.
`sqlite3 data/fresas.db ".backup copia.db"`). En `data/secret_key` está la
clave que firma las sesiones: si la borras, todo el mundo tendrá que volver a
entrar.

## Usuarios y seguridad

- Para entrar hace falta usuario y contraseña. Hay dos roles:
  **Usuario** (registra y consulta datos) y **Administrador** (además da de
  alta usuarios, cambia roles, restablece contraseñas y da de baja).
- Los administradores gestionan los usuarios en la pestaña **Usuarios**; cada
  uno puede cambiar su contraseña en **Mi cuenta**.
- Si se pierde la contraseña del administrador, se restablece en la
  Raspberry con `./venv/bin/python server.py crear-admin <usuario>`.
- Contraseñas guardadas con hash (scrypt), mínimo 8 caracteres.
- Tras 5 intentos fallidos de entrar, ese usuario queda bloqueado 15 minutos
  desde esa conexión.
- La sesión dura 30 días en cada dispositivo. Al cambiar o restablecer la
  contraseña, o al dar de baja a un usuario, se cierran sus sesiones abiertas.
- Cookie de sesión `HttpOnly`, `SameSite` y `Secure` (en producción), cabecera
  anti-CSRF obligatoria y cabeceras de seguridad (CSP, HSTS, anti-iframe).

## Desarrollo en local

```bash
cd fresas
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python server.py crear-admin admin
./venv/bin/python server.py
```

Abre <http://localhost:5001>. En local se usa HTTP; en producción
`FRESAS_HTTPS=1` y `FRESAS_PROXY=1` (los pone el servicio) activan la cookie
segura y la lectura de la IP real a través del túnel.

## Funcionalidades

### Campaña
Todo se agrupa por campaña de septiembre a agosto (plantación en octubre,
recogida de diciembre/enero a junio): la campaña 2026/27 va del 1-9-2026 al
31-8-2027. El selector de la cabecera cambia de campaña.

### Recolección
- Registro rápido por fecha, sector, trabajador (opcional), categoría, cajas y kg.
  Tras añadir un registro se mantienen fecha, sector y categoría para ir
  metiendo los de toda la cuadrilla seguidos.
- Categorías: Extra, Primera, Segunda e Industria (destrío).

### Cuaderno de campo
- Tratamientos fitosanitarios con producto, nº de registro, materia activa,
  plaga, dosis, plazo de seguridad y aplicador.
- **Control del plazo de seguridad**: la app avisa arriba de los sectores que
  no se pueden recolectar todavía y bloquea el registro de recolección en un
  sector con plazo en vigor (se puede forzar confirmando).
- Exportación a Excel del cuaderno de la campaña.

### Entregas
- Albaranes a cooperativa/almacén por categoría y kg. El precio €/kg se rellena
  cuando llega la liquidación (mientras tanto aparece como *pendiente*).

### Resumen
- Kg recolectados, días de recogida, kg/ha, kg entregados, importe liquidado
  y precio medio.
- Kg por semana y por categoría.
- Rendimiento por sector (kg/ha y g/planta) para comparar variedades.
- Kg, cajas y kg/día por trabajador.
- Exportación a Excel de la recolección y las entregas de la campaña.

## Endpoints del backend

Las peticiones que modifican datos deben llevar la cabecera
`X-Requested-With: fresas`.

| Ruta | Descripción |
|------|-------------|
| `POST /api/login` · `POST /api/logout` · `GET /api/me` | Sesión (todas las demás rutas exigen haber entrado) |
| `POST /api/me/password` | Cambiar la propia contraseña (`{"actual", "nueva"}`) |
| `GET/POST /api/usuarios` · `PUT /api/usuarios/<id>` | Gestión de usuarios (solo administradores) |
| `GET /api/meta` | Categorías, campañas con datos y campaña actual |
| `GET /api/<tabla>?campana=` | Lista registros (`fincas`, `sectores`, `trabajadores`, `recolecciones`, `entregas`, `tratamientos`) |
| `POST /api/<tabla>` | Crea un registro. En `recolecciones` devuelve 409 si hay plazo de seguridad en vigor, salvo que se envíe `"forzar": true` |
| `PUT /api/<tabla>/<id>` | Modifica un registro |
| `DELETE /api/<tabla>/<id>` | Borra un registro (409 si tiene registros asociados) |
| `GET /api/plazos?fecha=` | Sectores con plazo de seguridad en vigor (por defecto, hoy) |
| `GET /api/resumen?campana=` | Totales y estadísticas de la campaña |
| `GET /api/export/cuaderno?campana=` | Cuaderno de campo en Excel |
| `GET /api/export/campana?campana=` | Recolección y entregas en Excel |
