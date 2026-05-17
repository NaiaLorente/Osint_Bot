"""Orquestador OSINT: búsquedas en paralelo, formato, y búsqueda profunda por pregunta.

Funciones principales:
- run_full_search(query): para /search. Búsqueda multivariante (nombre + redes).
- fetch_top_pages(session): descarga texto de las páginas top de /search.
- targeted_search(person, question): fallback ligero si tras el LLM seguimos sin
  respuesta (legacy; con deep_question_search activo rara vez se usa).
- deep_question_search(person, question): NUEVA. Búsqueda exhaustiva orientada
  a la pregunta concreta. Genera 4-6 queries derivadas de la categoría de
  pregunta (edad, trabajo, estudios, familia, lugar, redes, aspecto, logros…),
  las ejecuta en paralelo, reordena por relevancia y descarga páginas nuevas.
- question_signature(question): firma simple para cachear búsquedas profundas
  por categoría (si ya buscamos "edad", no volvemos a buscar "edad" en la sesión).
"""

import asyncio
import html
import logging
import re

from sources.duckduckgo import search_web as search_duckduckgo_web
from sources.fetcher import fetch_page_text

logger = logging.getLogger(__name__)

# ─────────────────────────── Stopwords y tokenización ───────────────────────────

_STOPWORDS = {
    "que", "qué", "cual", "cuál", "como", "cómo", "donde", "dónde", "cuando",
    "cuándo", "quien", "quién", "quienes", "quiénes", "por", "para", "con",
    "sin", "del", "de", "la", "el", "los", "las", "un", "una", "unos", "unas",
    "y", "o", "u", "a", "en", "es", "se", "su", "sus", "al", "lo", "le", "les",
    "me", "te", "ti", "mi", "tu", "ya", "si", "no", "ha", "han", "hay",
    "esta", "está", "están", "estan", "este", "esto", "esa", "ese", "eso",
    "soy", "eres", "son", "fue", "fueron", "ser", "estar",
    "hace", "hacer", "dedica", "dedican", "trabaja", "trabajan", "tiene",
    "tienen", "vive", "viven", "sabes", "dime", "cuenta", "explica", "resume",
    "what", "who", "when", "where", "why", "how", "which", "the", "a", "an",
    "is", "are", "was", "were", "do", "does", "did", "of", "to", "in", "on",
    "and", "or", "for", "with", "about",
}


def _quote(query: str) -> str:
    q = query.strip()
    if not q or (q.startswith('"') and q.endswith('"')):
        return q
    return f'"{q}"' if len(q.split()) >= 2 else q


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"\w+", text.lower(), flags=re.UNICODE) if len(t) > 2]


def _extract_keywords(question: str) -> str:
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
    for k in ("snippet", "description", "body", "summary"):
        v = r.get(k)
        if v:
            return str(v)
    return ""


def _result_score(result: dict, terms: list[str]) -> int:
    if not terms:
        return 0
    text = " ".join([
        str(result.get("title") or ""),
        _snippet_of(result),
        str(result.get("url") or ""),
    ]).lower()
    return sum(1 for t in terms if t in text)


def _rerank(results: list[dict], query: str) -> list[dict]:
    terms = _tokenize(query)
    if not terms:
        return results
    return sorted(results, key=lambda r: _result_score(r, terms), reverse=True)


async def _search_one(loop, query: str, n: int = 5) -> list[dict]:
    try:
        results = await loop.run_in_executor(None, search_duckduckgo_web, query, n)
        return results or []
    except Exception as exc:  # noqa: BLE001
        logger.error("Error en búsqueda '%s': %s", query, exc)
        return []


# ──────────────────────── Búsqueda inicial multivariante ────────────────────────

async def run_full_search(query: str) -> dict:
    loop = asyncio.get_event_loop()
    quoted = _quote(query)

    variants: list[tuple[str, int]] = [
        (quoted, 7),
        (f"{quoted} site:linkedin.com", 3),
        (f"{quoted} site:instagram.com", 3),
        (f"{quoted} (site:twitter.com OR site:x.com)", 2),
        (f"{quoted} site:facebook.com", 2),
        (f"{quoted} (noticias OR entrevista OR perfil)", 3),
    ]

    all_batches = await asyncio.gather(
        *[_search_one(loop, q, n) for q, n in variants]
    )

    seen: set[str] = set()
    merged: list[dict] = []
    for batch in all_batches:
        for r in batch:
            url = r.get("url")
            if url and url not in seen:
                seen.add(url)
                merged.append(r)

    if not merged and quoted != query:
        merged = await _search_one(loop, query, 10)

    ranked = _rerank(merged, query)
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


# ─────────────────────────── Formato para Telegram ──────────────────────────────

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


# ─────────────────────── Descarga de páginas top de /search ─────────────────────

async def fetch_top_pages(query_or_session: str | dict) -> dict[str, str]:
    if isinstance(query_or_session, dict):
        query = query_or_session.get("query") or ""
        web = list(query_or_session.get("web") or [])
    else:
        query = query_or_session or ""
        web = []

    loop = asyncio.get_event_loop()
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


# ──────────────────────── Búsqueda dirigida ligera (legacy) ─────────────────────

async def targeted_search(
    person: str,
    question: str,
    existing_pages: dict | None = None,
) -> dict[str, str]:
    keywords = _extract_keywords(question)
    quoted = _quote(person)
    targeted_query = f"{quoted} {keywords}".strip() if keywords else quoted

    loop = asyncio.get_event_loop()
    results = await _search_one(loop, targeted_query, 5)
    if not results and keywords:
        results = await _search_one(loop, quoted, 5)
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


# ════════════════════════ Búsqueda profunda por pregunta ═══════════════════════

# Cada categoría: (lista de palabras que disparan la categoría,
#                  lista de plantillas de query — usan {quoted} para el nombre).
_QUESTION_PATTERNS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "edad": (
        ("edad", "años", "viejo", "vieja", "joven", "mayor",
         "nacimiento", "nació", "nacido", "nacida", "born", "age"),
        ('{quoted} "fecha de nacimiento"',
         '{quoted} nació OR nacido OR nacida',
         '{quoted} biografía edad',
         '{quoted} site:wikipedia.org'),
    ),
    "trabajo": (
        ("trabajo", "trabaja", "trabajaba", "empleo", "puesto", "cargo",
         "profesión", "profesion", "dedica", "ocupación", "ocupacion",
         "career", "job", "work", "occupation"),
        ('{quoted} site:linkedin.com',
         '{quoted} CV OR currículo OR curriculum',
         '{quoted} empleo OR puesto OR cargo',
         '{quoted} empresa OR trabaja'),
    ),
    "estudios": (
        ("estudios", "estudia", "estudió", "estudiaron", "carrera", "universidad",
         "facultad", "instituto", "máster", "master", "phd", "doctorado", "tesis",
         "grado", "licenciatura", "education", "studies"),
        ('{quoted} universidad OR facultad',
         '{quoted} tesis OR doctorado OR phd',
         '{quoted} máster OR grado OR licenciatura',
         '{quoted} site:researchgate.net OR site:dialnet.unirioja.es'),
    ),
    "familia": (
        ("familia", "hijos", "hija", "hijo", "pareja", "novia", "novio",
         "casado", "casada", "matrimonio", "boda", "esposa", "esposo",
         "married", "spouse", "wife", "husband", "children", "kids", "family"),
        ('{quoted} familia OR pareja',
         '{quoted} hijos OR hija OR hijo',
         '{quoted} casado OR casada OR boda OR matrimonio',
         '{quoted} esposa OR esposo OR novia OR novio'),
    ),
    "lugar": (
        ("vive", "viven", "reside", "residencia", "domicilio", "ciudad",
         "país", "pais", "localidad", "barrio", "from", "lives", "based",
         "dónde", "donde"),
        ('{quoted} vive OR reside',
         '{quoted} ciudad OR país OR localidad',
         '{quoted} origen OR procedencia'),
    ),
    "redes": (
        ("instagram", "twitter", "linkedin", "tiktok", "facebook",
         "redes", "social media", "perfil", "usuario", "@"),
        ('{quoted} site:instagram.com',
         '{quoted} site:tiktok.com',
         '{quoted} (site:twitter.com OR site:x.com)',
         '{quoted} site:facebook.com',
         '{quoted} site:youtube.com'),
    ),
    "famoso": (
        ("famoso", "famosa", "conocido", "conocida", "mediático", "mediatica",
         "celebridad", "celebrity", "famous", "popular", "notable"),
        ('{quoted} entrevista',
         '{quoted} noticias',
         '{quoted} biografía OR perfil',
         '{quoted} site:wikipedia.org'),
    ),
    "logros": (
        ("logros", "premio", "premios", "medalla", "medallas", "ganó", "gano",
         "ganador", "ganadora", "campeón", "campeona", "won", "award", "winner"),
        ('{quoted} premio OR galardón',
         '{quoted} ganador OR campeón',
         '{quoted} medalla OR torneo OR competición'),
    ),
    "publicaciones": (
        ("publicaciones", "publicación", "libro", "libros", "artículo",
         "artículos", "papers", "paper", "publicó", "publico", "autor",
         "autora", "escritor", "escritora", "book", "publication"),
        ('{quoted} publicaciones OR papers',
         '{quoted} libro OR autor OR autora',
         '{quoted} site:scholar.google.com OR site:researchgate.net'),
    ),
    "aspecto": (
        ("aspecto", "apariencia", "físico", "fisico", "pelo", "cabello",
         "ojos", "altura", "complexión", "complexion", "barba", "tatuaje",
         "vestimenta", "ropa", "foto", "fotos", "imagen", "imágenes",
         "look", "appearance", "hair", "eyes"),
        ('{quoted} foto OR retrato',
         '{quoted} perfil OR fotografía',
         '{quoted} site:instagram.com'),
    ),
    "contacto": (
        ("email", "correo", "teléfono", "telefono", "contacto", "contact",
         "phone", "mail"),
        ('{quoted} contacto OR email',
         '{quoted} site:linkedin.com'),
    ),
}


def question_signature(question: str) -> str:
    """Firma de la pregunta basada en categorías que dispara. Para cachear búsquedas.

    Dos preguntas con la misma firma (p.ej. '¿qué edad tiene?' y '¿cuándo nació?')
    activan las mismas búsquedas profundas, así que se cachean juntas.
    """
    q = question.lower()
    matches = [cat for cat, (triggers, _) in _QUESTION_PATTERNS.items()
               if any(t in q for t in triggers)]
    return "+".join(sorted(matches)) or "general"


def _generate_question_queries(person: str, question: str) -> list[str]:
    """4-6 consultas optimizadas para una pregunta concreta sobre la persona."""
    quoted = _quote(person)
    q_lower = question.lower()
    queries: list[str] = []
    matched = False

    for cat, (triggers, templates) in _QUESTION_PATTERNS.items():
        if any(t in q_lower for t in triggers):
            for tmpl in templates:
                queries.append(tmpl.format(quoted=quoted))
            matched = True

    # Variante con keywords de la pregunta (siempre útil)
    keywords = _extract_keywords(question)
    if keywords:
        queries.append(f"{quoted} {keywords}")

    if not matched:
        # Pregunta no clasificada: variantes generales amplias
        queries.append(f"{quoted} biografía OR perfil")
        queries.append(f"{quoted} entrevista OR noticias")

    # Dedupe preservando orden
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[:7]  # tope: 7 consultas en paralelo


async def deep_question_search(
    person: str,
    question: str,
    existing_pages: dict | None = None,
    max_new_pages: int = 8,
) -> dict[str, str]:
    """Búsqueda exhaustiva orientada a una pregunta sobre la persona.

    Lanza N queries específicas en paralelo, ranquea los resultados nuevos por
    relevancia (peso doble al nombre, peso simple a los términos de la pregunta)
    y descarga las top N páginas nuevas con concurrencia limitada.

    Devuelve {url: texto} solo con las páginas nuevas (no presentes en
    existing_pages). Si no hay nada nuevo o útil, devuelve dict vacío.
    """
    existing_pages = existing_pages or {}
    queries = _generate_question_queries(person, question)
    if not queries:
        return {}

    logger.info("Deep search [%s]: %d queries", question_signature(question), len(queries))

    loop = asyncio.get_event_loop()
    batches = await asyncio.gather(*[_search_one(loop, q, 5) for q in queries])

    # Merge + dedupe contra páginas ya cacheadas
    seen_urls: set[str] = set(existing_pages.keys())
    merged: list[dict] = []
    for batch in batches:
        for r in batch:
            url = r.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                merged.append(r)

    if not merged:
        return {}

    # Ranking: nombre pesa el doble que los términos de la pregunta
    person_terms = _tokenize(person)
    question_terms = [t for t in _tokenize(question) if t not in _STOPWORDS]

    def _score(r: dict) -> int:
        text = " ".join([
            str(r.get("title") or ""),
            _snippet_of(r),
            str(r.get("url") or ""),
        ]).lower()
        p_score = sum(1 for t in person_terms if t in text)
        q_score = sum(1 for t in question_terms if t in text)
        return p_score * 2 + q_score

    ranked = sorted(merged, key=_score, reverse=True)

    # Descarga con concurrency limitada
    sem = asyncio.Semaphore(4)

    async def _fetch(url: str) -> tuple[str, str | None]:
        async with sem:
            text = await loop.run_in_executor(None, fetch_page_text, url)
        return url, text

    candidate_urls = [r["url"] for r in ranked[:max_new_pages] if r.get("url")]
    fetch_results = await asyncio.gather(
        *[_fetch(u) for u in candidate_urls], return_exceptions=True
    )

    pages: dict[str, str] = {}
    for result in fetch_results:
        if isinstance(result, Exception):
            continue
        url, text = result
        if isinstance(text, str) and text:
            pages[url] = text
    logger.info("Deep search trajo %d páginas nuevas", len(pages))
    return pages
