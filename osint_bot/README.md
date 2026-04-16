# Bot OSINT de Telegram

Bot de Telegram que, dado un nombre o nombre de usuario, consulta **fuentes
abiertas** (Wikipedia, GitHub, LinkedIn vía enlace, X/Twitter vía enlace,
noticias y web general) y devuelve un informe ordenado. Además permite
hacer preguntas en lenguaje natural sobre la persona usando la API de
Claude como motor de Q&A sobre el contexto recopilado.

## Características

- Búsquedas en paralelo en varias fuentes abiertas.
- Fuentes: Wikipedia (API), **Wikidata (SPARQL — datos estructurados)**,
  GitHub (API), noticias y web general (DDG), enlaces a LinkedIn y X/Twitter.
- Informe formateado (HTML) para Telegram con enlaces clicables.
- Modo Q&A con Claude que responde **solo con la información recopilada**
  (no inventa datos, no deduce información sensible).
- Sesión por chat: cada chat tiene su propia persona activa.
- Autorización opcional por lista blanca de IDs de Telegram.

## Arquitectura

```
osint_bot/
├── bot.py                 # Arranque del bot y registro de handlers
├── config.py              # Carga de .env
├── requirements.txt
├── .env.example
├── handlers/
│   ├── commands.py        # /start, /help, /search, /ask, /clear
│   └── messages.py        # Texto libre -> /search o /ask (heurística)
├── sources/
│   ├── wikipedia.py       # Wikipedia API
│   ├── wikidata.py        # Wikidata SPARQL (datos estructurados)
│   ├── github.py          # GitHub REST API
│   └── duckduckgo.py      # DDG: web, LinkedIn, X/Twitter, noticias
├── services/
│   ├── osint.py           # Orquesta y formatea
│   └── llm.py             # Cliente Anthropic (Claude)
└── storage/
    └── sessions.py        # Estado en memoria por chat
```

## Instalación

Requiere Python 3.10+.

```bash
git clone <este-proyecto>
cd osint_bot
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edita .env y rellena TELEGRAM_TOKEN y ANTHROPIC_API_KEY
python bot.py
```

### Desplegar con Docker (recomendado para VPS)

```bash
cp .env.example .env && nano .env   # rellena las credenciales
docker compose up -d --build
docker compose logs -f               # ver logs en vivo
```

El contenedor se reinicia solo si falla (`restart: unless-stopped`),
tiene el log rotado a 10 MB × 3 ficheros y corre como usuario no root.

### Ejecutar los tests

```bash
pip install pytest
TELEGRAM_TOKEN=dummy ANTHROPIC_API_KEY=dummy pytest tests/ -v
```

Los tests incluidos no requieren red ni credenciales: validan las
funciones puras (heurística de preguntas, troceado para Telegram,
escapado de HTML y formateo de cada fuente).

### Obtener credenciales

- **Telegram:** habla con [@BotFather](https://t.me/BotFather) y envía
  `/newbot`. Te dará el token.
- **Anthropic:** crea una key en <https://console.anthropic.com/>.
- **GitHub** (opcional, recomendado): un token *fine-grained* sin permisos
  eleva el rate limit de 60 a 5 000 peticiones/hora.
- **Tu ID de Telegram** (opcional, para restringir acceso): habla con
  [@userinfobot](https://t.me/userinfobot).

## Uso

Una vez el bot esté corriendo, desde Telegram:

| Comando                    | Descripción                                         |
|---------------------------|-----------------------------------------------------|
| `/start`, `/help`         | Muestra la ayuda.                                   |
| `/search Ada Lovelace`    | Busca en todas las fuentes y muestra informe.       |
| `/search torvalds`        | Si coincide, trae el perfil de GitHub.              |
| `/ask ¿Dónde estudió?`    | Pregunta sobre la última búsqueda de este chat.     |
| `/clear`                  | Borra la sesión de este chat.                       |

También puedes escribir directamente sin comando:
- `Linus Torvalds` → hace una búsqueda.
- `¿a qué se dedica?` (con sesión activa) → responde sobre esa persona.

## Extender el bot

Añadir una nueva fuente es sencillo:

1. Crea `sources/mi_fuente.py` con una función `def search_mi_fuente(q) -> dict|list`.
2. Regístrala en `services/osint.py` dentro de `run_full_search` y
   añade su bloque en `format_results`.

Ideas de fuentes adicionales que son **compatibles con OSINT público y
sus ToS**: `arXiv`, `Crossref` para publicaciones, `Mastodon` API,
`Wikidata` SPARQL, dominios `/humans.txt`, Gravatar (email hash), etc.

## Consideraciones legales y éticas (importante)

Aunque los datos sean públicos, **el tratamiento automatizado de información
sobre personas físicas identificables entra dentro del RGPD (UE) y la
LOPDGDD (España)**. Antes de usar este bot sobre terceros:

- Asegúrate de tener una base jurídica válida para el tratamiento (interés
  legítimo documentado, consentimiento, obligación legal…).
- No crees perfiles que crucen datos sensibles (salud, ideología,
  orientación, religión).
- Respeta los ToS de cada plataforma. Este bot **no scrapea LinkedIn ni X**;
  solo resuelve enlaces a perfiles públicos vía un buscador.
- No lo uses para acosar, doxear o vigilar a nadie.
- Ofrece mecanismos de borrado (`/clear`) y no persistas datos más tiempo
  del necesario. Por defecto, este bot solo guarda la sesión **en memoria**.

## Limitaciones conocidas

- LinkedIn y X/Twitter solo se resuelven como enlaces públicos; no se
  extrae el contenido del perfil.
- El buscador DDG a veces aplica rate limits; en ese caso, esa sección
  aparecerá vacía y el resto del informe seguirá funcionando.
- GitHub se consulta como *username exacto*; si pasas un nombre completo
  con espacios, esa fuente devolverá vacío (y es lo correcto).

## Licencia

MIT. Úsalo bajo tu responsabilidad.
