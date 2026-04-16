"""Configuración: lee variables de entorno de .env."""
import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()  # opcional, sube rate limits

# Modelo de Claude para el Q&A. Sonnet ofrece buena relación calidad/precio.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5").strip()

# Idioma por defecto para búsquedas en Wikipedia.
WIKIPEDIA_LANG = os.getenv("WIKIPEDIA_LANG", "es").strip()

# Quiénes pueden usar el bot (IDs de Telegram separados por coma). Vacío = todos.
_raw_allowed = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = (
    {int(x) for x in _raw_allowed.split(",") if x.strip().isdigit()}
    if _raw_allowed
    else set()
)

if not TELEGRAM_TOKEN:
    raise RuntimeError("Falta TELEGRAM_TOKEN en el entorno (.env)")
if not ANTHROPIC_API_KEY:
    raise RuntimeError("Falta ANTHROPIC_API_KEY en el entorno (.env)")
