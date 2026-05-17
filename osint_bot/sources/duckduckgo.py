"""Búsqueda vía DuckDuckGo con caché.

Se usa para búsquedas web generales y para *resolver enlaces* a perfiles
sociales (LinkedIn, X/Twitter) sin scrapear esos sitios directamente,
lo cual respeta sus términos de uso.

Con caché para evitar repetir búsquedas idénticas.
"""
import logging

from ddgs import DDGS

from utils.rate_limiter import SEARCH_CACHE

logger = logging.getLogger(__name__)


def _search(query: str, max_results: int = 5) -> list[dict]:
    # Intenta obtener del caché
    cached = SEARCH_CACHE.get(query, "duckduckgo")
    if cached is not None:
        logger.debug(f"DuckDuckGo (caché): {query}")
        return cached[:max_results]

    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results, region="us-en"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Error en DDG (%s): %s", query, exc)
        return []

    results = []
    for r in raw:
        results.append(
            {
                "title": r.get("title"),
                "url": r.get("href") or r.get("url"),
                "snippet": r.get("body"),
            }
        )
    
    # Cachea el resultado
    SEARCH_CACHE.set(query, "duckduckgo", results)
    return results


def search_web(query: str, max_results: int = 8) -> list[dict]:
    """Búsqueda web general.

    Devuelve los primeros resultados relevantes de búsqueda web, como un motor
    de búsqueda, para mostrar los 8 enlaces principales.
    """
    return _search(query, max_results=max_results)


def search_linkedin(name: str) -> list[dict]:
    """Devuelve posibles perfiles públicos de LinkedIn para `name`."""
    return _search(f'site:linkedin.com/in "{name}"', max_results=3)


def search_twitter(name: str) -> list[dict]:
    """Devuelve posibles perfiles públicos de X/Twitter para `name`."""
    return _search(
        f'(site:twitter.com OR site:x.com) "{name}"', max_results=3
    )


def search_instagram(name: str) -> list[dict]:
    """Devuelve posibles perfiles públicos de Instagram para `name`."""
    return _search(f'site:instagram.com "{name}"', max_results=3)


def search_github(name: str) -> list[dict]:
    """Devuelve posibles perfiles públicos de GitHub para `name`."""
    return _search(f'site:github.com "{name}"', max_results=2)


def search_news(name: str) -> list[dict]:
    """Noticias recientes (DDG news)."""
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.news(name, max_results=5))
    except Exception as exc:  # noqa: BLE001
        logger.error("Error en DDG news: %s", exc)
        return []
    return [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "snippet": r.get("body"),
            "date": r.get("date"),
            "source": r.get("source"),
        }
        for r in raw
    ]
