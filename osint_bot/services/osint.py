"""Orquestador OSINT: lanza las búsquedas en paralelo y formatea la salida.

Mejoras vs. versión anterior:
- Búsqueda multivariante en paralelo: nombre entre comillas + LinkedIn +
  Instagram + Twitter/X + Facebook + variantes de noticias.
- Reranking por relevancia: resultados que contienen todos los términos del
  nombre suben por encima de los que solo comparten apellido.
- `fetch_top_pages` reutiliza los resultados de la sesión y filtra páginas
  irrelevantes antes de descargarlas.
- `targeted_search` construye consultas de calidad a partir de keywords de
  la pregunta (sin stopwords), conservando el nombre entre comillas.
"""

import asyncio
import html
import logging
import re

from sources.duckduckgo import search_web as search_duckduckgo_web
from sources.fetcher import fetch_page_text
from sources.google_search import search_google_web

logger = logging.getLogger(__name__)

# Stopwords mínimas para limpiar preguntas antes de buscar.
_STOPWORDS = {
    # Español
    "que", "qué", "cual", "cuál", "como", "cómo", "donde", "dónde", "cuando",
    "cuándo", "quien", "quién", "quienes", "quiénes", "por", "para", "con",
    "sin", "del", "de", "la", "el", "los", "las", "un", "una", "unos", "unas",
    "y", "o", "u", "a", "en", "es", "se", "su", "sus", "al", "lo", "le", "les",
    "me", "te", "ti", "mi", "tu", "ya", "si", "no", "ha", "han", "hay",
    "esta", "está", "están", "estan", "este", "esto", "esa", "ese", "eso",
    "soy", "eres", "son", "fue", "fueron", "ser", "estar",
    # Verbos genéricos que NO añaden información a la búsqueda
    "hace", "hacer", "dedica", "dedican", "trabaja", "trabajan", "tiene",
    "tienen", "vive", "viven", "sabes", "dime", "cuenta", "explica", "resume",
    # Inglés
    "what", "who", "when", "where", "why", "how", "which", "the", "a", "an",
    "is", "are", "was", "were", "do", "does", "did", "of", "to", "in", "on",
    "and", "or", "for", "with", "about",
}


def _quote(query: str) -> str:
    """Envuelve la consulta entre comillas si tiene 2+ palabras y no estaba ya."""
    q = query.strip()
    if not q or (q.startswith('"') and q.endswith('"')):
        return q
    return f'"{q}"' if len(q.split()) >= 2 else q


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"\w+", text.lower(), flags=re.UNICODE) if len(t) > 2]


def _extract_keywords(question: str) -> str:
    """Saca términos significativos de una pregunta para añadirlos a una búsqueda."""
    tokens = _tokenize(question)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return " ".join(out[:5])


def _snippet_of(r: dict) -> str:
    """Lee el snippet con varios nombres de campo posibles (Google, DDG, etc)."""
    for k in ("snippet", "description", "body", "summary"):
        v = r.get(k)
        if v:
            return str(v)
    return ""


def _result_score(result: dict, terms: list[str]) -> int:
    """Número de términos del nombre que aparecen en título/snippet/URL."""
    if not terms:
        return 0
    text = " ".join([
        str(result.get("title") or ""),
        _snippet_of(result),
        str(result.get("url") or ""),
    ]).lower()
    return sum(1 for t in terms if t in text)


def _rerank(results: list[dict], query: str) -> list[dict]:
    """Ordena resultados de más a menos términos del nombre coincidentes."""
    terms = _tokenize(query)
    if not terms:
        return results
    # Usamos sorted estable: empates conservan el orden original (que es relevancia del buscador)
    return sorted(results, key=lambda r: _result_score(r, terms), reverse=True)


async def _search_one(loop, query: str, n: int = 5) -> list[dict]:
    """Una búsqueda con fallback Google -> DuckDuckGo."""
    try:
        results = await loop.run_in_executor(None, search_google_web, query, n)
        if not results:
            results = await loop.run_in_executor(None, search_duckduckgo_web, query, n)
        return results or []
    except Exception as exc:  # noqa: BLE001
        logger.error("Error en búsqueda '%s': %s", query, exc)
        return []


async def run_full_search(query: str) -> dict:
    """Búsqueda multivariante en paralelo + rerank por relevancia."""
    loop = asyncio.get_event_loop()
    quoted = _quote(query)

    # Variantes: (consulta, nº resultados deseados).
    variants: list[tuple[str, int]] = [
        (quoted, 7),                                          # general, nombre exacto
        (f"{quoted} site:linkedin.com", 3),
        (f"{quoted} site:instagram.com", 3),
        (f"{quoted} (site:twitter.com OR site:x.com)", 2),
        (f"{quoted} site:facebook.com", 2),
        (f"{quoted} (noticias OR entrevista OR perfil)", 3),
    ]

    all_batches = await asyncio.gather(
        *[_search_one(loop, q, n) for q, n in variants]
    )

    # Merge preservando orden, deduplicando por URL.
    seen: set[str] = set()
    merged: list[dict] = []
    for batch in all_batches:
        for r in batch:
            url = r.get("url")
            if url and url not in seen:
                seen.add(url)
                merged.append(r)

    # Si todas las variantes con comillas fallaron, prueba sin comillas.
    if not merged and quoted != query:
        merged = await _search_one(loop, query, 10)

    ranked = _rerank(merged, query)

    # Aviso si NINGÚN resultado contiene el nombre completo; útil para gente
    # poco indexada (p.ej. Naia Lorente Martinez) — el bot avisa en vez de
    # devolver ruido sin contexto.
    terms = _tokenize(query)
    full_match = any(_result_score(r, terms) >= len(terms) for r in ranked[:10]) if terms else True

    results: dict = {
        "query": query,
        "web": ranked[:10],
        "history": [],
        "full_name_matched": full_match,
    }
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
        for idx, r in enumerate(web[:10], start=1):
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

    if results.get("full_name_matched") is False:
        parts.append(
            "⚠️ <i>Ningún resultado contiene el nombre completo. "
            "Mostrando lo más cercano; la información puede ser sobre otras "
            "personas con apellidos similares.</i>"
        )
        parts.append("")

    web = results.get("web") or []
    if web:
        parts.append("<b>Resultados web (10 primeros enlaces)</b>")
        for idx, r in enumerate(web[:10], start=1):
            parts.append(
                f"{idx}. {_link(r.get('title') or r.get('url'), r.get('url'))}"
            )
        parts.append("")
    else:
        parts.append("<b>Resultados web:</b> sin resultados")
        parts.append("")

    parts.append("<i>Usa /ask &lt;pregunta&gt; para preguntar sobre estos enlaces.</i>")
    return "\n".join(parts)


async def fetch_top_pages(query_or_session: str | dict) -> dict[str, str]:
    """Descarga texto de las páginas más relevantes ya devueltas por la búsqueda.

    Reutiliza `session['web']` si está disponible — no relanza una nueva búsqueda.
    Filtra previamente por relevancia: solo descarga páginas cuyo título/snippet
    contiene al menos un término del nombre. Si ninguna pasa el filtro, usa
    todas como fallback para no quedarse sin contexto.
    """
    if isinstance(query_or_session, dict):
        query = query_or_session.get("query") or ""
        web = list(query_or_session.get("web") or [])
    else:
        query = query_or_session or ""
        web = []

    loop = asyncio.get_event_loop()

    # Si la sesión no traía resultados, los pedimos ahora (con comillas).
    if not web and query:
        web = await _search_one(loop, _quote(query), 10)

    terms = _tokenize(query)

    def _is_relevant(r: dict) -> bool:
        return _result_score(r, terms) >= 1 if terms else True

    relevant = [r for r in web if _is_relevant(r)] or web

    pages: dict[str, str] = {}
    for r in relevant[:5]:
        url = r.get("url")
        if not url or url in pages:
            continue
        text = await loop.run_in_executor(None, fetch_page_text, url)
        if text:
            pages[url] = text
    return pages


async def targeted_search(
    person: str,
    question: str,
    existing_pages: dict | None = None,
) -> dict[str, str]:
    """Búsqueda dirigida a la pregunta del usuario.

    Construye una consulta de calidad: nombre entre comillas + palabras clave
    extraídas de la pregunta (sin stopwords). Reintenta sin keywords si el
    primer intento no devuelve nada.
    """
    keywords = _extract_keywords(question)
    quoted = _quote(person)
    targeted_query = f"{quoted} {keywords}".strip() if keywords else quoted

    loop = asyncio.get_event_loop()
    results = await _search_one(loop, targeted_query, 5)

    # Si no hubo resultados con keywords, prueba solo con el nombre entrecomillado.
    if not results and keywords:
        results = await _search_one(loop, quoted, 5)

    # Y como último recurso, sin comillas (puede que el nombre exacto no esté indexado).
    if not results and quoted != person:
        results = await _search_one(loop, f"{person} {keywords}".strip(), 5)

    existing_pages = existing_pages or {}
    pages: dict[str, str] = {}
    for r in results:
        url = r.get("url")
        if not url or url in existing_pages or url in pages:
            continue
        text = await loop.run_in_executor(None, fetch_page_text, url)
        if text:
            pages[url] = text
    return pages
