# Bot OSINT de Telegram

Bot de Telegram que recibe un nombre o usuario, busca resultados web en fuentes abiertas y devuelve un informe ordenado en Telegram. También permite hacer preguntas sobre la última búsqueda usando un modelo de IA sobre el contexto de los enlaces recopilados.

## Qué hace realmente este bot

- Ejecuta una búsqueda web usando Google Custom Search API si está configurado.
- Si no hay credenciales de Google Search, usa DuckDuckGo como fallback.
- Devuelve los primeros enlaces relevantes ordenados.
- Guarda el contexto de la búsqueda en la sesión del chat.
- Permite preguntar con `/ask <pregunta>` sobre la última búsqueda.
- Usa OpenRouter / Gemini para generar respuestas basadas únicamente en el contexto recopilado.

## Estructura del proyecto

\`\`\`
osint_bot/
├── bot.py                 # Arranque del bot y registro de handlers
├── config.py              # Lectura de variables de entorno
├── requirements.txt       # Dependencias Python necesarias
├── .env.example           # Ejemplo de variables de entorno
├── handlers/
│   ├── commands.py        # /start, /help, /search, /ask, /clear
│   └── messages.py        # Texto libre -> /search o /ask
├── sources/
│   ├── duckduckgo.py      # Búsqueda web y enlaces públicos
│   ├── google_search.py   # Google Custom Search (opcional)
│   └── fetcher.py         # Descarga y limpia texto de páginas web
├── services/
│   ├── osint.py           # Orquesta búsquedas y formatea resultados
│   └── llm.py             # Cliente de OpenRouter / Gemini para Q&A
└── storage/
    └── sessions.py        # Estado en memoria por chat
\`\`\`

## Instalación

Requisitos:
- Python 3.10+
- Git
- Docker (opcional)

\`\`\`bash
git clone <repositorio>
cd osint_bot
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env
\`\`\`

Edita `.env` y completa las variables necesarias antes de arrancar el bot.

### Ejecutar localmente

\`\`\`bash
python bot.py
\`\`\`

### Ejecutar con Docker

\`\`\`bash
copy .env.example .env
docker compose up -d --build
\`\`\`

### Probar los tests

\`\`\`bash
pip install pytest
TELEGRAM_TOKEN=dummy OPENROUTER_API_KEY=dummy pytest tests/ -v
\`\`\`

## Variables de configuración (`.env`)

- `TELEGRAM_TOKEN` — token del bot de Telegram.
- `OPENROUTER_API_KEY` — clave de OpenRouter para el modelo Gemini.
- `GITHUB_TOKEN` — token de GitHub opcional para mejorar el rate limit si se usa GitHub.
- `GOOGLE_SEARCH_API_KEY` — clave de Google Search API opcional.
- `GOOGLE_SEARCH_ENGINE_ID` — ID de motor de búsqueda de Google opcional.
- `LLM_MODEL` — modelo Gemini a usar (por defecto `gemini-2.5-flash-lite`).
- `WIKIPEDIA_LANG` — idioma de Wikipedia si se utiliza la fuente de Wikipedia (no está integrada activamente en este momento).
- `ALLOWED_USER_IDS` — IDs de Telegram autorizados, separados por comas.

> Nota: el flujo actual usa principalmente Google Search/DuckDuckGo y OpenRouter/Gemini. Las funciones de Wikipedia, GitHub y Wikidata no se encuentran integradas en el flujo activo del bot.

## Uso en Telegram

Comandos principales:

| Comando                     | Descripción                                         |
|----------------------------|-----------------------------------------------------|
| `/start`, `/help`          | Muestra ayuda básica.                                |
| `/search <nombre o usuario>` | Busca resultados web y muestra un informe.         |
| `/ask <pregunta>`          | Pregunta sobre la última búsqueda en este chat.      |
| `/clear`                   | Borra la sesión del chat actual.                     |

### Ejemplos

- `/search Ada Lovelace`
- `/search torvalds`
- `/ask ¿Dónde estudió?`
- `/ask ¿Cuál es su profesión?`

### Mensajes libres

- Si envías un nombre o usuario sin comando, el bot intentará hacer una búsqueda.
- Si escribes una pregunta y hay sesión activa, el bot lo tratará como `/ask`.

## Qué entregar

Para que el profesor pueda evaluar fácilmente tu trabajo, entrega:

1. El repositorio completo con todo el código.
2. El archivo `.env.example` sin credenciales reales.
3. `README.md` con pasos claros de instalación y uso.
4. Un video breve mostrando:
   - configuración de `.env`
   - arranque del bot
   - uso de `/start`, `/search`, `/ask` y `/clear`
   - resultados reales en Telegram

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

## Limitaciones actuales

- El bot no extrae perfiles completos de LinkedIn ni X/Twitter; solo muestra enlaces públicos.
- Sin Google Search configurado, usa DuckDuckGo.
- El Q&A solo responde con información disponible en los enlaces y páginas descargadas.

## Licencia

MIT.