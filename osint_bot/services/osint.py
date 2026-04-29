"""Orquestador OSINT: lanza las búsquedas en paralelo y formatea la salida."""

"""La lógica de OSINT"""

import asyncio
import html
import logging

from sources.wikipedia import search_wikipedia
from sources.wikidata import search_wikidata
from sources.github import search_github
from sources.duckduckgo import (
    search_web,
    search_linkedin,
    search_twitter,
    search_news,
)

logger = logging.getLogger(__name__)


async def run_full_search(query: str) -> dict:
    """Ejecuta todas las fuentes concurrentemente."""
    loop = asyncio.get_event_loop()

    tasks = {
        "wikipedia": loop.run_in_executor(None, search_wikipedia, query),
        "wikidata": loop.run_in_executor(None, search_wikidata, query),
        "github": loop.run_in_executor(None, search_github, query),
        "linkedin": loop.run_in_executor(None, search_linkedin, query),
        "twitter": loop.run_in_executor(None, search_twitter, query),
        "news": loop.run_in_executor(None, search_news, query),
        "web": loop.run_in_executor(None, search_web, query, 8),
    }

    results: dict = {"query": query}
    for key, task in tasks.items():
        try:
            results[key] = await task
        except Exception as exc:  # noqa: BLE001
            logger.error("Fuente %s falló: %s", key, exc)
            results[key] = None

    return results


# -- Formateo para Telegram (HTML es más robusto que Markdown para URLs) --


def _esc(text: str | None) -> str:
    return html.escape(text) if text else ""


def _link(title: str | None, url: str | None) -> str:
    if not url:
        return _esc(title) or ""
    return f'<a href="{_esc(url)}">{_esc(title or url)}</a>'


def format_results(results: dict) -> str:
    parts: list[str] = [
        f"<b>Resultados OSINT para:</b> <code>{_esc(results['query'])}</code>",
        "",
    ]

    # --- Wikipedia ---
    w = results.get("wikipedia")
    if w:
        parts.append(f"<b>Wikipedia</b> ({w.get('lang', '?')})")
        parts.append(_link(w["title"], w["url"]))
        summary = w["summary"]
        if len(summary) > 600:
            summary = summary[:600].rsplit(" ", 1)[0] + "…"
        parts.append(f"<i>{_esc(summary)}</i>")
        parts.append("")
    else:
        parts.append("<b>Wikipedia:</b> sin resultados")
        parts.append("")

    # --- Wikidata ---
    wd = results.get("wikidata")
    if wd:
        parts.append(f"<b>Wikidata</b> — {_link(wd['label'], wd['wikidata_url'])}")
        if wd.get("birth"):
            line = f"• Nacimiento: {_esc(wd['birth'])}"
            if wd.get("death"):
                line += f" | Fallecimiento: {_esc(wd['death'])}"
            parts.append(line)
        if wd.get("gender"):
            parts.append(f"• Género: {_esc(wd['gender'])}")
        if wd.get("countries"):
            parts.append(f"• Nacionalidad: {_esc(', '.join(wd['countries']))}")
        if wd.get("occupations"):
            parts.append(f"• Ocupación: {_esc(', '.join(wd['occupations'][:5]))}")
        if wd.get("employers"):
            parts.append(f"• Empleadores: {_esc(', '.join(wd['employers'][:5]))}")
        if wd.get("website"):
            parts.append(f"• Web oficial: {_esc(wd['website'])}")
        parts.append("")

    # --- GitHub ---
    g = results.get("github")
    if g:
        parts.append(f"<b>GitHub</b> — {_link('@' + g['login'], g['url'])}")
        if g.get("name"):
            parts.append(f"• Nombre: {_esc(g['name'])}")
        if g.get("bio"):
            parts.append(f"• Bio: {_esc(g['bio'])}")
        if g.get("company"):
            parts.append(f"• Empresa: {_esc(g['company'])}")
        if g.get("location"):
            parts.append(f"• Ubicación: {_esc(g['location'])}")
        if g.get("blog"):
            parts.append(f"• Web: {_esc(g['blog'])}")
        if g.get("twitter_username"):
            parts.append(f"• Twitter: @{_esc(g['twitter_username'])}")
        parts.append(
            f"• Repos públicos: {g.get('public_repos', 0)} | "
            f"Seguidores: {g.get('followers', 0)}"
        )
        if g.get("top_repos"):
            parts.append("• Top repos:")
            for repo in g["top_repos"][:3]:
                desc = f" — {_esc(repo['description'])}" if repo.get("description") else ""
                parts.append(
                    f"   · {_link(repo['name'], repo['url'])} "
                    f"{repo['stars']}{desc}"
                )
        parts.append("")
    else:
        parts.append("<b>GitHub:</b> sin usuario público con ese handle")
        parts.append("")

    # --- LinkedIn ---
    li = results.get("linkedin") or []
    if li:
        parts.append("<b>LinkedIn</b> (posibles perfiles)")
        for r in li[:3]:
            parts.append(f"• {_link(r['title'], r['url'])}")
        parts.append("")

    # --- Twitter / X ---
    tw = results.get("twitter") or []
    if tw:
        parts.append("<b>X / Twitter</b> (posibles perfiles)")
        for r in tw[:3]:
            parts.append(f"• {_link(r['title'], r['url'])}")
        parts.append("")

    # --- News ---
    news = results.get("news") or []
    if news:
        parts.append("<b>Noticias recientes</b>")
        for r in news[:4]:
            meta = f" <i>({_esc(r.get('source') or '')}, {_esc(r.get('date') or '')})</i>"
            parts.append(f"• {_link(r['title'], r['url'])}{meta}")
        parts.append("")

    # --- Web general ---
    web = results.get("web") or []
    if web:
        parts.append("<b>Otros resultados web</b>")
        for r in web[:5]:
            parts.append(f"• {_link(r['title'], r['url'])}")
        parts.append("")

    parts.append("<i>Usa /ask &lt;pregunta&gt; para preguntar sobre estos datos.</i>")
    return "\n".join(parts)
