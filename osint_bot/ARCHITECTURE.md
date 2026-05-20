# Arquitectura y funcionamiento del bot OSINT

Este documento describe en profundidad cómo funciona el bot, cómo se relacionan sus componentes y qué busca exactamente en cada paso.

## 1. Visión general

El bot es un servicio de Telegram que recibe consultas de usuario y responde con:

- un informe de enlaces web relevantes (`/search`),
- respuestas en lenguaje natural basadas en el contenido de páginas web y
  resultados anteriores (`/ask`),
- búsqueda profunda orientada a la pregunta (`/deep`),
- y un resumen de sesión con `/report`.

Su flujo principal es:

1. El usuario envía un nombre o usuario.
2. El bot busca en la web usando DuckDuckGo.
3. El bot devuelve los mejores enlaces en Telegram.
4. El usuario puede preguntar sobre esa búsqueda con `/ask` o `/deep`.
5. El bot descarga páginas adicionales y usa un modelo de IA para responder.

## 2. Componentes principales

### 2.1 `bot.py`

- Arranca el bot de Telegram.
- Crea la aplicación con `Application.builder().token(TELEGRAM_TOKEN).build()`.
- Registra handlers:
  - `/start`
  - `/help`
  - `/search`
  - `/ask`
  - `/deep`
  - `/report`
  - `/clear`
  - mensajes de texto libre
- Ejecuta polling con `app.run_polling(allowed_updates=Update.ALL_TYPES)`.

### 2.2 `config.py`

Carga las variables de entorno desde `.env` y define:

- `TELEGRAM_TOKEN`
- `OPENROUTER_API_KEY`
- `GITHUB_TOKEN`
- `GOOGLE_SEARCH_API_KEY` — opcional para Google Custom Search legado; no se usa en el flujo activo.
- `GOOGLE_SEARCH_ENGINE_ID` — opcional para Google Custom Search legado; no se usa en el flujo activo.
- `LLM_MODEL`
- `WIKIPEDIA_LANG`
- `ALLOWED_USER_IDS`

`TELEGRAM_TOKEN` y `OPENROUTER_API_KEY` son obligatorios, el resto es opcional.

### 2.3 `storage/sessions.py`

Guarda estado en memoria por chat Telegram:

- `set_session(chat_id, data)`
- `get_session(chat_id)`
- `clear_session(chat_id)`

El estado se mantiene mientras el proceso esté vivo.

## 3. Flujo de mensajes

### 3.1 Comandos: `handlers/commands.py`

- `/start` y `/help`: muestran el mensaje de bienvenida con ayuda.
- `/search <texto>`: busca y muestra resultados.
- `/ask <pregunta>`: responde preguntas usando la última búsqueda.
- `/deep <pregunta>`: ejecuta una búsqueda profunda orientada a la pregunta.
- `/report`: genera un informe de la sesión actual.
- `/clear`: borra la sesión del chat.

### 3.2 Mensajes libres: `handlers/messages.py`

Si el usuario envía texto sin comando:

- si ya hay sesión y el texto parece pregunta, se ejecuta `/ask`.
- en caso contrario, se ejecuta `/search`.

La heurística de pregunta considera signos de interrogación y palabras como:
`qué`, `quién`, `dónde`, `cómo`, `who`, `what`, `why`, etc.

## 4. Flujo de búsqueda (`/search`)

### 4.1 `services/osint.py` → `run_full_search()`

1. Ejecutar varias búsquedas en paralelo con DuckDuckGo:
   - `query`
   - `query site:linkedin.com`
   - `query site:instagram.com`
   - `query (site:twitter.com OR site:x.com)`
   - `query site:facebook.com`
   - `query (noticias OR entrevista OR perfil)`
2. Ejecución en paralelo de:
   - `search_wikipedia(query)`
   - `search_wikidata(query)`
3. Fusionar resultados web eliminando URLs repetidas y ordenar los enlaces más relevantes.
4. Construir un diccionario `results` con:
   - `query`
   - `web` (lista de enlaces)
   - `history` (lista vacía inicialmente)
   - `html_links` (resumen en HTML de los enlaces)
   - `wikipedia`, `wikidata`

### 4.2 `search_duckduckgo_web()`

En `sources/duckduckgo.py`:

- usa la librería `ddgs` para buscar en DuckDuckGo.
- devuelve enlaces, títulos y snippets.
- también tiene funciones auxiliares para LinkedIn, X/Twitter, GitHub,
  Instagram y noticias.
- la búsqueda de GitHub no forma parte de la búsqueda inicial de `/search`.
  En su lugar, `sources/github.py` se activa luego como enriquecimiento de `/ask`
  cuando se detectan URLs `github.com`.

### 4.4 Salida para Telegram

`format_results()` en `services/osint.py` genera un texto en HTML con:

- el término de búsqueda,
- hasta 10 enlaces web,
- una nota invitando a usar `/ask`.

Ese texto se envía en uno o varios mensajes cortos.

## 5. Flujo de pregunta (`/ask`)

### 5.1 `handlers/commands.py` → `perform_question()`

1. Recupera la sesión del chat.
2. Si no hay sesión, pide primero `/search`.
3. Si es la primera pregunta del chat, llama a `fetch_top_pages(session)`.
4. Si la pregunta contiene URLs, descarga esas páginas extra.
5. Llama a `answer_question(session, question)`.
6. Si la respuesta indica falta de datos, hace `targeted_search()` y vuelve a
   generar la respuesta.
7. Guarda la nueva `history` y `pages` en la sesión.

### 5.2 `fetch_top_pages()`

- recibe la sesión o el query.
- busca los 5 mejores resultados con DuckDuckGo.
- descarga el texto de cada URL con `fetch_page_text()`.
- devuelve un diccionario `pages[url] = texto`.

### 5.3 `answer_question()` en `services/llm.py`

- prepara el contexto eliminando campos redundantes.
- construye un bloque de contexto con:
  - datos OSINT en JSON,
  - `html_links` (enlaces del resultado inicial),
  - `pages` descargadas.
- usa el historial de la sesión para formar un chat multi-turno.
- llama a Gemini con `chat.send_message(...)`.
- devuelve el texto del modelo.

### 5.4 Reconocimiento de falta de respuesta

Si la respuesta del modelo contiene frases como:

- "no encuentro ese dato"
- "no tengo esa información"
- "no hay información"

el bot considera que no encontró la respuesta y ejecuta `targeted_search()`.

### 5.5 `targeted_search()`

- construye una consulta dirigida: `query + pregunta`.
- busca con DuckDuckGo.
- descarga texto de las mejores URLs nuevas.
- añade esas páginas a la sesión y vuelve a preguntar al modelo.

## 6. Extracción de texto de páginas (`sources/fetcher.py`)

`fetch_page_text(url)` hace:

1. comprueba si el dominio es gated (Facebook, Instagram, TikTok);
   si es así omite la URL.
2. descarga la página con `requests` y encabezados de navegador.
3. parsea HTML con `BeautifulSoup`.
4. extrae meta tags útiles (`og:title`, `description`, etc.).
5. extrae JSON-LD de tipo `Person`, `ProfilePage` u `Organization`.
6. elimina `script`, `style`, `nav`, `footer`, `aside` y `header`.
7. limpia el texto y lo recorta a 4000 caracteres.
8. si detecta una página de login, devuelve solo metadatos.

Esto permite que el modelo reciba texto relevante sin ruido.

## 7. Modelos y LLM

### 7.1 `services/llm.py`

- usa `google.generativeai` para conectar con OpenRouter / Gemini.
- el modelo es configurable mediante `LLM_MODEL`.
- utiliza un `SYSTEM_PROMPT` muy estricto:
  - responde solo con datos del contexto,
  - no inventa información,
  - menciona fuente cuando es posible,
  - responde en el idioma de la pregunta.

### 7.2 Contexto que recibe el modelo

- la búsqueda inicial en JSON,
- los enlaces visibles en `html_links`,
- texto descargado de páginas web,
- historial de preguntas/respuestas previas.

## 8. Componentes opcionales y no activos

El proyecto incluye varios módulos `sources/` que aportan distintos tipos de
información. El flujo principal de `/search` usa directamente estas fuentes:

- `sources/duckduckgo.py` — búsqueda web principal y consultas específicas a
  sitios como LinkedIn, Instagram, X/Twitter, Facebook y noticias.
- `sources/wikipedia.py` — busca la página de Wikipedia en el idioma configurado.
- `sources/wikidata.py` — obtiene datos estructurados de Wikidata.

Además, el flujo de Q&A (`/ask` y `/deep`) enriquece la sesión con:

- `sources/structured.py` — extrae estructura schema.org / Open Graph de páginas
  descargadas.
- `sources/github.py` — consulta la API pública de GitHub SOLO si aparecen URLs
  `github.com` en los resultados o en las páginas descargadas.
- `services/vision.py` — analiza imágenes públicas cuando la pregunta es visual.

**Nota importante:** `sources/wikipedia.py` depende de `wikipediaapi`, por lo que
esta librería debe aparecer en `requirements.txt` para que el proyecto sea
instalable y usable sin pasos manuales adicionales.

## 9. Configuración y variables de entorno

Variables clave:

- `TELEGRAM_TOKEN` — token del bot Telegram.
- `OPENROUTER_API_KEY` — clave para OpenRouter/Gemini.
- `GOOGLE_SEARCH_API_KEY` — opcional para Google Custom Search legado; no se usa en el flujo activo.
- `GOOGLE_SEARCH_ENGINE_ID` — opcional para Google Custom Search legado; no se usa en el flujo activo.
- `GITHUB_TOKEN` — opcional para GitHub.
- `LLM_MODEL` — modelo Gemini (por defecto `gemini-2.5-flash-lite`).
- `WIKIPEDIA_LANG` — idioma para Wikipedia si se usa.
- `ALLOWED_USER_IDS` — IDs permitidos, separados por comas.

## 10. Resumen de acciones internas

### `/search` hace:

- `run_full_search(query)`
- lanza varias búsquedas DuckDuckGo en paralelo con variantes de perfil y noticias
  (incluye LinkedIn, Instagram, X/Twitter, Facebook, notas de prensa).
- ejecuta en paralelo `search_wikipedia(query)` y `search_wikidata(query)`.
- fusiona y deduplica resultados web.
- ordena por relevancia y construye `results` con:
  - `query`
  - `web`
  - `history`
  - `html_links`
  - `wikipedia`
  - `wikidata`
- guarda la sesión con `set_session(chat_id, results)`.
- responde con un informe HTML y botones rápidos cuando es posible.

### `/ask` hace:

- recupera sesión con `get_session(chat_id)`.
- si no hay sesión, pide primero `/search`.
- si no hay páginas descargadas, ejecuta `fetch_top_pages(session)`.
- extrae URLs mencionadas en la pregunta y descarga su contenido cuando aparecen.
- enriquece con datos estructurados, GitHub y visión si procede.
- llama a `answer_question(session, question)` para generar la respuesta con Gemini.
- si la respuesta parece no tener datos, guarda un estado de búsqueda profunda.
- guarda `session['pages']`, `session['history']` y los enrichments.
- responde con el texto final.

### `/deep` hace:

- ejecuta una búsqueda profunda orientada a la pregunta.
- trae más páginas relevantes que no se descargaron con `/ask`.
- vuelve a enriquecer con schema.org/OG, GitHub y visión.
- reintenta `targeted_search()` como último recurso si la respuesta sigue siendo pobre.

### `/report` hace:

- genera un informe de la sesión actual.
- incluye enlaces top, páginas analizadas, imágenes descritas y conversación.
- lo envía como texto o como archivo si excede el límite de Telegram.

## 11. Limitaciones clave

- El bot está diseñado para un uso personal y guarda datos solo en memoria.
- No hay persistencia entre reinicios.
- No extrae contenido privado ni hace login en plataformas.
- No está diseñado para escalar a múltiples instancias sin cambiar el
  almacenamiento de sesión.
- El flujo actual usa Wikipedia y Wikidata en `/search`.
- `sources/github.py` solo se activa como enriquecimiento de `/ask` y `/deep`
  cuando aparecen URLs `github.com`.

## 12. Próximos pasos de mejora

- Integrar `sources/github.py` de forma más explícita en el enriquecimiento de
  `/ask` y `/deep`.
- Añadir persistencia de sesión con Redis o base de datos.
- Controlar mejor los límites de tasa y el uso de proxies para búsquedas web.
- Añadir pruebas de integración del flujo `/ask` y `/deep` con el modelo.

---

Este documento explica el funcionamiento real del proyecto tal como está hoy.
Usa `ARCHITECTURE.md` para que el profesor entienda qué hace cada parte y cómo
se conectan los módulos.
