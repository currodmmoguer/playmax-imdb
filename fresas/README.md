# 🍓 Fresas — gestión de campaña

Aplicación web para llevar una explotación de fresa tal y como se trabaja en
Huelva: fincas con sectores de macrotúnel, temporeros por cuadrillas,
recolección diaria por categorías, entregas a la cooperativa y el cuaderno de
campo de tratamientos fitosanitarios.

Es independiente del comparador Playmax/IMDb del resto del repositorio
(Flask + SQLite + HTML/JS sin dependencias), pensada para correr en la misma
Raspberry Pi y usarse desde el móvil en el campo.

## Puesta en marcha

```bash
cd fresas
python3 -m venv venv
./venv/bin/pip install flask openpyxl
./venv/bin/python server.py
```

Abre <http://localhost:5001> (o `http://<ip-de-la-raspberry>:5001`). El puerto
se cambia con la variable `PORT`. Los datos se guardan en `fresas/data/fresas.db`
(excluido de git; haz copia de ese fichero).

La primera vez la app te lleva a **Fincas**: da de alta la finca, después sus
**Sectores** (variedad, hectáreas, nº de plantas, fecha de plantación) y los
**Trabajadores**.

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

| Ruta | Descripción |
|------|-------------|
| `GET /api/meta` | Categorías, campañas con datos y campaña actual |
| `GET /api/<tabla>?campana=` | Lista registros (`fincas`, `sectores`, `trabajadores`, `recolecciones`, `entregas`, `tratamientos`) |
| `POST /api/<tabla>` | Crea un registro. En `recolecciones` devuelve 409 si hay plazo de seguridad en vigor, salvo que se envíe `"forzar": true` |
| `PUT /api/<tabla>/<id>` | Modifica un registro |
| `DELETE /api/<tabla>/<id>` | Borra un registro (409 si tiene registros asociados) |
| `GET /api/plazos?fecha=` | Sectores con plazo de seguridad en vigor (por defecto, hoy) |
| `GET /api/resumen?campana=` | Totales y estadísticas de la campaña |
| `GET /api/export/cuaderno?campana=` | Cuaderno de campo en Excel |
| `GET /api/export/campana?campana=` | Recolección y entregas en Excel |
