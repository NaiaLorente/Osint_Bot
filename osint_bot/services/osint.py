"""Orquestador OSINT: lanza las búsquedas en paralelo y formatea la salida."""

"""La lógica de OSINT"""

import asyncio
import html
import logging

from sources.duckduckgo import search_web as search_duckduckgo_web
from sources.google_search import search_google_web

logger = logging.getLogger(__name__)


async def run_full_search(query: str) -> dict:
    """Ejecuta una búsqueda web usando Google primero y DuckDuckGo como fallback."""
    loop = asyncio.get_event_loop()

    try:
        web = await loop.run_in_executor(None, search_google_web, query, 8)
        if not web:
            web = await loop.run_in_executor(None, search_duckduckgo_web, query, 8)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error en búsqueda web: %s", exc)
        web = []

    results: dict = {"query": query, "web": web, "history": []}
    results["html_links"] = _build_html_context(results)
    return results


# -- Formateo para Telegram (HTML es más robusto que Markdown para URLs) --


def _esc(text: str | None) -> str:
    return html.escape(text) if text else ""


def _link(title: str | None, url: str | None) -> str:
    if not url:
        return _esc(title) or ""
    return f'<a href="{_esc(url)}">{_esc(title or url)}</a>'


def _build_html_context(results: dict) -> str:
    sections: list[str] = []

    web = results.get("web") or []
    if web:
        sections.append("<b>Resultados web</b>")
        for idx, r in enumerate(web[:8], start=1):
            sections.append(
                f"{idx}. {_link(r.get('title') or r.get('url'), r.get('url'))}"
            )
        sections.append("")

    return "\n".join(sections)


def format_results(results: dict) -> str:
    parts: list[str] = [
        f"<b>Resultados de búsqueda para:</b> <code>{_esc(results['query'])}</code>",
        "",
    ]

    web = results.get("web") or []
    if web:
        parts.append("<b>Resultados web (8 primeros enlaces)</b>")
        for idx, r in enumerate(web[:8], start=1):
            parts.append(
                f"{idx}. {_link(r.get('title') or r.get('url'), r.get('url'))}"
            )
        parts.append("")
    else:
        parts.append("<b>Resultados web:</b> sin resultados")
        parts.append("")

    parts.append("<i>Usa /ask &lt;pregunta&gt; para preguntar sobre estos enlaces.</i>")
    return "\n".join(parts)
