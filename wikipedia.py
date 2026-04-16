"""Búsqueda en Wikipedia usando la API oficial."""
import logging

import wikipediaapi

from config import WIKIPEDIA_LANG

logger = logging.getLogger(__name__)


def search_wikipedia(name: str, lang: str | None = None) -> dict | None:
    """Devuelve un resumen de la página de Wikipedia si existe.

    Si no existe en el idioma solicitado, intenta en inglés como fallback.
    """
    lang = lang or WIKIPEDIA_LANG
    try:
        wiki = wikipediaapi.Wikipedia(
            user_agent="OSINT-Telegram-Bot/1.0 (https://example.com)",
            language=lang,
        )
        page = wiki.page(name)
        if not page.exists():
            if lang != "en":
                return search_wikipedia(name, "en")
            return None

        return {
            "title": page.title,
            "summary": page.summary[:1500],
            "url": page.fullurl,
            "lang": lang,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Error en Wikipedia: %s", exc)
        return None
