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

## Endpoints del backend

| Ruta | Descripción |
|------|-------------|
| `GET /api/status` | Estado de la conexión con Playmax y del dataset de IMDb |
| `GET /api/search?q=` | Busca fichas en Playmax |
| `GET /api/explore?type=&order=&start=` | Navega el catálogo (tipo: 1 series, 2 películas, 3 documentales; orden: 9 populares, 6 mejor valoradas, 1 nuevas) |
| `GET /api/ficha/<id>` | Detalle de la ficha + valoración IMDb + diferencia |
| `GET /api/my_fichas` | Tus fichas marcadas (todas las secciones) con valoración IMDb si ya está resuelta |
| `POST /api/imdb/resolve` | Resuelve el imdbId de hasta 15 fichas (`{"ids": [...]}`) y persiste el mapeo |
| `POST /api/imdb/update` | Vuelve a descargar el dataset de IMDb |

La vista **"Mis fichas"** resuelve los IDs de IMDb progresivamente (1 llamada
a Playmax por ficha, respetando el límite). El mapeo ficha↔IMDb se guarda en
SQLite, así que solo es lento la primera vez (~8 min para ~860 fichas);
después la tabla carga al instante.

## Límites de la API de Playmax

20 peticiones cada 10 segundos por IP. Las fichas se cachean en memoria
durante 1 hora para no agotar el límite.
