"""Scraping de Webmii: agrega presencia web pública de una persona."""

import logging
import re
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE = "https://webmii.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}
# Dominios internos de Webmii que no aportan info útil
_SKIP_DOMAINS = frozenset({"webmii.com", "google.com", "googletagmanager.com"})


def search_webmii(name: str) -> list[dict]:
    """Devuelve los perfiles y enlaces externos que Webmii encuentra para `name`."""
    try:
        url = f"{_BASE}/people?n={quote_plus(name)}"
        r = requests.get(url, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        results: list[dict] = []
        seen: set[str] = set()

        # Extrae puntuación de visibilidad si existe
        score_tag = soup.find(class_=re.compile(r"score|visibility|index", re.I))
        score_text = score_tag.get_text(strip=True) if score_tag else ""

        for a in soup.find_all("a", href=True):
            href: str = a["href"].strip()
            if not href.startswith("http"):
                continue
            # Filtrar dominios internos/publicitarios
            domain = href.split("/")[2].lstrip("www.")
            if any(skip in domain for skip in _SKIP_DOMAINS):
                continue
            if href in seen:
                continue
            seen.add(href)

            text = a.get_text(strip=True) or href
            results.append({"title": text[:120], "url": href, "snippet": score_text})
            if len(results) >= 6:
                break

        return results
    except Exception as exc:
        logger.error("Error en Webmii: %s", exc)
        return []
