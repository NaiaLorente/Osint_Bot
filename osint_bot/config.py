"""Configuración: lee variables de entorno de .env."""
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GOOGLE_SEARCH_API_KEY = os.getenv("GOOGLE_SEARCH_API_KEY", "").strip()
GOOGLE_SEARCH_ENGINE_ID = os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip()

# Modelo de OpenRouter
CLAUDE_MODEL = os.getenv("LLM_MODEL", "meta-llama/llama-3.1-8b-instruct").strip()

WIKIPEDIA_LANG = os.getenv("WIKIPEDIA_LANG", "es").strip()

_raw_allowed = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = (
    {int(x) for x in _raw_allowed.split(",") if x.strip().isdigit()}
    if _raw_allowed
    else set()
)

if not TELEGRAM_TOKEN:
    raise RuntimeError("Falta TELEGRAM_TOKEN en el entorno (.env)")
if not OPENROUTER_API_KEY:
    raise RuntimeError("Falta OPENROUTER_API_KEY en el entorno (.env)")