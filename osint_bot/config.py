"""Configuración: lee variables de entorno de .env."""
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
GEMINI_API_KEY = (
    os.getenv("GEMINI_API_KEY") or os.getenv("OPENROUTER_API_KEY") or ""
).strip()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

LLM_MODEL_NAME = os.getenv("LLM_MODEL", "gemini-2.5-flash").strip()
WIKIPEDIA_LANG = os.getenv("WIKIPEDIA_LANG", "es").strip()

_raw_allowed = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = (
    {int(x) for x in _raw_allowed.split(",") if x.strip().isdigit()}
    if _raw_allowed
    else set()
)

if not TELEGRAM_TOKEN:
    raise RuntimeError("Falta TELEGRAM_TOKEN en el entorno (.env)")
if not GEMINI_API_KEY:
    raise RuntimeError("Falta GEMINI_API_KEY en el entorno (.env)")