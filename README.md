# Playmax vs IMDB

Aplicación web que compara las valoraciones de películas y series entre
[Playmax](https://playmax.mx) e IMDb.

## Cómo funciona

- El backend (Flask) hace de proxy sobre la API de Playmax, de forma que la
  `apiKey` nunca llega al navegador.
- La relación con IMDb sale del campo `externalLinks` que devuelve el endpoint
  `ficha` de Playmax (entrada con `name: "IMDb"` y `externalId: "tt…"`).
- Las valoraciones de IMDb se obtienen del dataset oficial
  [`title.ratings.tsv.gz`](https://datasets.imdbws.com/) (gratuito, actualizado
  a diario), que se descarga automáticamente al primer arranque y se carga en
  SQLite (`data/imdb.db`, ~1,7 M de títulos). No hace falta ninguna API key de
  IMDb/OMDb. El servidor lo refresca automáticamente cuando tiene más de 24
  horas, sin cortes (la tabla nueva se construye aparte y se intercambia al
  final).

## Puesta en marcha

```bash
python3 -m venv venv
./venv/bin/pip install flask requests
./venv/bin/python server.py
```

Abre <http://localhost:5000> (o `http://<ip-de-la-raspberry>:5000` desde otro
equipo de la red).

## Configuración

La API key de Playmax (de [Tus Apps](https://playmax.mx/tusapps.php)) se lee
del fichero `.env` (excluido de git):

```
PLAYMAX_API_KEY=tu_api_key
```

Además la app necesita la **autorización del usuario** (`authKey`): la API de
Playmax exige que las apps usen el flujo de `user_authorization`. La authKey
se guarda en `data/auth_key.txt`. Si falta o caduca, la barra de estado de la
web muestra un botón **"Autorizar app"** que genera una nueva y abre la página
de autorización de Playmax (también puedes autorizarla desde el Panel de
Control → Aplicaciones autorizadas de tu cuenta).

## Funcionalidades principales

### Exploración del catálogo
- **Por Playmax:** Ordena por popularidad, mejor valoradas o más nuevas según Playmax
- **Por IMDb:** Ordena por mejor valoradas según IMDb (con datos visuales de Playmax)
- Filtros por tipo: películas, series, documentales

### "Mis fichas"
- Ve todas tus fichas marcadas con sus valoraciones en ambas plataformas
- Filtra por estado de marcado (siguiendo, pendiente, favorita, vista, abandonada)
- Filtra por estado de serie (finalizada, esperando, en producción, cancelada)
- Ordena por cualquier columna
- Descarga tus fichas como Excel

## Endpoints del backend

| Ruta | Descripción |
|------|-------------|
| `GET /api/status` | Estado de la conexión con Playmax y del dataset de IMDb |
| `GET /api/search?q=` | Busca fichas en Playmax |
| `GET /api/explore?type=&order=&start=` | Navega por Playmax (tipo: 1 series, 2 películas, 3 documentales; orden: 9 populares, 6 mejor valoradas, 1 nuevas) |
| `GET /api/explore_imdb?type=&start=` | Navega por IMDb ordenadas por rating (tipo: 1 series, 2 películas, 3 documentales) |
| `GET /api/ficha/<id>` | Detalle de la ficha + valoración IMDb + diferencia |
| `GET /api/my_fichas` | Tus fichas marcadas (todas las secciones) con valoración IMDb |
| `POST /api/series-status` | Estado actual de series (`{"ids": [...]}`) |
| `POST /api/imdb/resolve` | Resuelve el imdbId de hasta 15 fichas (`{"ids": [...]}`) y persiste el mapeo |
| `POST /api/imdb/update` | Vuelve a descargar el dataset de IMDb |

### Rendimiento
- **Mapeo IMDb:** La primera vez tarda (~8 min para ~860 fichas). Después carga al instante.
- **Estados de serie:** Se cargan en background en lotes de 5 sin bloquear la UI
- Las fichas se cachean en memoria durante 1 hora para no agotar el límite de Playmax

## Límites de la API de Playmax

20 peticiones cada 10 segundos por IP. Las fichas se cachean en memoria
durante 1 hora para no agotar el límite.
