# Bot OSINT de Telegram

Bot de Telegram que recibe un nombre o usuario, busca resultados web en fuentes abiertas y devuelve un informe ordenado en Telegram. También permite hacer preguntas sobre la última búsqueda usando un modelo de IA que trabaja con el contexto recopilado.

## Qué hace realmente este bot

- Ejecuta una búsqueda multivariante usando DuckDuckGo.
- No depende de Google Search activa ni de Google Custom Search API.
- Recopila contexto adicional de Wikipedia, Wikidata y Webmii en paralelo.
- `/search` muestra resultados web estructurados y enlaces relevantes.
- `/ask` responde preguntas usando la información de la sesión actual.
- `/deep` hace una búsqueda profunda orientada a la pregunta.
- `/report` genera un informe completo de la sesión.
- Usa Gemini (a través de OpenRouter) para generar respuestas en lenguaje natural.

## Estructura del proyecto

```
osint_bot/
├── bot.py                 # Arranque del bot y registro de handlers
├── config.py              # Lectura de variables de entorno
├── requirements.txt       # Dependencias Python necesarias
├── .env.example           # Ejemplo de variables de entorno
├── handlers/
│   ├── commands.py        # /start, /help, /search, /ask, /deep, /report, /clear
│   └── messages.py        # Texto libre -> /search o /ask según heurística
├── sources/
│   ├── duckduckgo.py      # Búsqueda web y enlaces públicos
│   ├── wikipedia.py       # Búsqueda en Wikipedia
│   ├── wikidata.py        # Búsqueda en Wikidata
│   ├── webmii.py          # Presencia web agregada
│   ├── github.py          # Enriquecimiento de GitHub para urls github.com
│   ├── fetcher.py         # Descarga y limpia texto de páginas web
│   ├── images.py          # Extrae imágenes de páginas para visión
│   └── structured.py      # Extrae schema.org / Open Graph de páginas
├── services/
│   ├── osint.py           # Orquesta búsquedas, descarga páginas y formatea resultados
│   └── llm.py             # Cliente de OpenRouter / Gemini para Q&A
└── storage/
    └── sessions.py        # Estado en memoria por chat
```

## Instalación

Requisitos:
- Python 3.10+
- Git
- Docker (opcional)

```bash
git clone <repositorio>
cd osint_bot
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env
```

Edita `.env` y completa las variables necesarias antes de arrancar el bot.

### Ejecutar localmente

```bash
python bot.py
```

### Ejecutar con Docker

```bash
copy .env.example .env
docker compose up -d --build
```

### Probar los tests

```bash
pip install pytest
TELEGRAM_TOKEN=dummy OPENROUTER_API_KEY=dummy pytest tests/ -v
```

## Variables de configuración (`.env`)

- `TELEGRAM_TOKEN` — token del bot de Telegram.
- `OPENROUTER_API_KEY` — clave de OpenRouter para el modelo Gemini.
- `GITHUB_TOKEN` — token de GitHub opcional para mejorar el rate limit si se usa GitHub en enriquecimiento.
- `GOOGLE_SEARCH_API_KEY` — clave de Google Search API opcional (no usada en el flujo activo).
- `GOOGLE_SEARCH_ENGINE_ID` — ID de motor de búsqueda de Google opcional (no usada en el flujo activo).
- `LLM_MODEL` — modelo Gemini a usar (por defecto `gemini-2.5-flash-lite`).
- `WIKIPEDIA_LANG` — idioma de Wikipedia para las consultas.
- `ALLOWED_USER_IDS` — IDs de Telegram autorizados, separados por comas.

> Nota: el flujo actual usa DuckDuckGo + Wikipedia + Wikidata + Webmii. GitHub solo se usa como enriquecimiento en `/ask` y `/deep` cuando hay URLs `github.com`.

## Uso en Telegram

Comandos principales:

| Comando                     | Descripción                                         |
|----------------------------|-----------------------------------------------------|
| `/start`, `/help`           | Muestra ayuda básica.                                |
| `/search <nombre o usuario>`| Busca resultados web y muestra un informe.           |
| `/ask <pregunta>`           | Pregunta sobre la última búsqueda en este chat.      |
| `/deep <pregunta>`          | Ejecuta una búsqueda profunda orientada a la pregunta. |
| `/report`                   | Genera un informe de la sesión actual.               |
| `/clear`                    | Borra la sesión del chat actual.                     |

### Ejemplos

- `/search Ada Lovelace`
- `/search torvalds`
- `/ask ¿Dónde estudió?`
- `/ask ¿Cuál es su profesión?`

### Mensajes libres

- Si envías un nombre o usuario sin comando, el bot intentará hacer una búsqueda.
- Si escribes una pregunta y hay sesión activa, el bot lo tratará como `/ask`.
- Si respondes a un resultado ambiguo con más contexto, el bot refina la búsqueda.

## Qué hace este proyecto

- `/search` lanza varias búsquedas DuckDuckGo con variantes de perfil, noticias y resultados generales.
- En paralelo consulta Wikipedia, Wikidata y Webmii.
- Fusiona resultados web, depura duplicados y ordena por relevancia.
- `/ask` usa los enlaces y páginas descargadas para responder con Gemini.
- `/deep` busca más páginas relevantes según la pregunta e intenta un último fallback de búsqueda direccionada.
- `/report` genera un resumen de la sesión con enlaces, páginas y preguntas.

## Flujo de búsqueda real

1. El usuario inicia con `/search <persona>`.
2. El bot ejecuta búsquedas DuckDuckGo y obtiene enlaces relevantes.
3. Al mismo tiempo, consulta `Wikipedia`, `Wikidata` y `Webmii` para enriquecer el resultado.
4. Devuelve un informe con enlaces web y datos estructurados.
5. El usuario puede preguntar con `/ask` o `/deep`.
6. En `/ask` y `/deep`, el bot descarga el texto de las páginas top y extrae datos estructurados.
7. Si hay URLs `github.com`, el bot usa `sources/github.py` para traer perfil y repositorios.
8. Si la pregunta es visual, el bot usa visión sobre imágenes públicas encontradas en las páginas.

## Arquitectura clave

- `bot.py` arranca el bot y registra los comandos y handlers.
- `handlers/commands.py` define los flujos de `/search`, `/ask`, `/deep`, `/report` y `/clear`.
- `handlers/messages.py` decide si un mensaje libre es búsqueda o pregunta.
- `services/osint.py` orquesta las búsquedas, descarga páginas y construye los resultados.
- `services/llm.py` crea el prompt y llama a Gemini para generar respuestas de Q&A.
- `sources/` contiene cada fuente de datos y los extractores de página.
- `storage/sessions.py` guarda sesión en memoria por chat.

## Notas importantes

- El flujo principal no usa Google Search activo.
- GitHub se usa solo como enriquecimiento posterior cuando hay URLs `github.com`.
- Las búsquedas de `/search` son multivariantes y no se limitan a una sola fuente.
- La sesión se mantiene en memoria y se pierde al reiniciar el bot.

## Limitaciones actuales

- No hay persistencia de datos entre reinicios.
- No se hace login en servicios privados.
- No es una solución de scraping de alto volumen.
- Algunas búsquedas pueden devolver enlaces irrelevantes por la naturaleza de la web pública.

## Cómo hacer el video

Orden sugerido:
1. Explica el propósito del bot.
2. Muestra `.env.example` y menciona las credenciales necesarias.
3. Arranca el bot localmente o con Docker.
4. En Telegram, envía `/start` y revisa la ayuda.
5. Haz una búsqueda con `/search`.
6. Haz una pregunta con `/ask` basada en esa búsqueda.
7. Muestra `/clear` y explica que borra la sesión.

## Consideraciones éticas

- Usa solo información pública.
- Respeta la privacidad y las leyes (RGPD/LOPDGDD).
- No hagas búsquedas de personas con fines de acoso o doxxing.

## Licencia

MIT.