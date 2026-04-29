"""Búsqueda web usando Google Custom Search API.

Este módulo intenta devolver los primeros resultados de Google para una
consulta, siempre que se proporcionen las credenciales necesarias.
Si no hay clave configurada, devuelve una lista vacía y el bot puede
caer de nuevo a DuckDuckGo.
"""

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

GOOGLE_SEARCH_API_KEY = os.getenv("GOOGLE_SEARCH_API_KEY", "").strip()
GOOGLE_SEARCH_ENGINE_ID = os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip()

API_URL = "https://www.googleapis.com/customsearch/v1"


def search_google_web(query: str, max_results: int = 8) -> list[dict[str, str]]:
    """Devuelve los primeros resultados de Google Search si hay credenciales."""
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_SEARCH_ENGINE_ID:
        logger.warning("No hay credenciales de Google Search configuradas.")
        return []

    params: dict[str, Any] = {
        "key": GOOGLE_SEARCH_API_KEY,
        "cx": GOOGLE_SEARCH_ENGINE_ID,
        "q": query,
        "num": min(max_results, 10),
    }

    try:
        response = requests.get(API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.error("Error en Google Search API: %s", exc)
        return []

    items = data.get("items", [])
    results: list[dict[str, str]] = []
    for item in items[:max_results]:
        results.append(
            {
                "title": item.get("title", "Sin título"),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
        )
    return results
