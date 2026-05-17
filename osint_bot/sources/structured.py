"""Extracción de datos estructurados de HTML público (JSON-LD, Open Graph, microdata).

Las páginas modernas exponen datos legibles por máquina mediante schema.org.
Wikipedia, fichas universitarias, GitHub, ORCID, ResearchGate, prensa, etc.
publican objetos Person/Organization/ScholarlyArticle con campos como
jobTitle, affiliation, birthDate, sameAs, alumniOf, etc.

Esto NO es scraping invasivo: es leer datos que la página declara
explícitamente como abiertos para indexación.

Archivo destinado a: sources/structured.py
"""
import json
import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
}


def extract_structured(html: str) -> list[dict]:
    """Devuelve todos los bloques de datos estructurados encontrados en el HTML.

    Fuentes (en este orden): JSON-LD, Open Graph + Twitter Card, microdata.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error parseando HTML: %s", exc)
        return []

    blocks: list[dict] = []

    # 1) JSON-LD: el más rico cuando está presente
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = (script.string or script.get_text() or "").strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # A veces traen comentarios o coma final; intentamos limpiarlo
            cleaned = re.sub(r",\s*([}\]])", r"\1", text)
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                continue
        _flatten_jsonld(data, blocks)

    # 2) Open Graph + Twitter Card (siempre útil)
    og: dict[str, str] = {}
    for meta in soup.find_all("meta"):
        prop = (meta.get("property") or meta.get("name") or "").strip()
        if not prop:
            continue
        if any(prop.startswith(p) for p in ("og:", "article:", "profile:", "twitter:")):
            content = (meta.get("content") or "").strip()
            if content:
                og[prop] = content
    if og:
        blocks.append({"@type": "OpenGraph", **og})

    # 3) Microdata simple (itemtype="https://schema.org/Person" etc.)
    for scope in soup.find_all(attrs={"itemscope": True}):
        itemtype = scope.get("itemtype", "")
        if not itemtype:
            continue
        item: dict[str, Any] = {"@type": itemtype.rsplit("/", 1)[-1]}
        for prop in scope.find_all(attrs={"itemprop": True}, recursive=True):
            key = prop.get("itemprop", "")
            val = (
                prop.get("content")
                or prop.get("href")
                or prop.get("src")
                or prop.get_text(strip=True)
            )
            if key and val:
                item[key] = val
        if len(item) > 1:
            blocks.append(item)

    return blocks


def _flatten_jsonld(data: Any, out: list[dict]) -> None:
    """JSON-LD puede venir como dict, lista, o con @graph anidado."""
    if isinstance(data, list):
        for item in data:
            _flatten_jsonld(item, out)
    elif isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                _flatten_jsonld(item, out)
        else:
            out.append(data)


# ─── Resumen útil para OSINT ───────────────────────────────────────────────

_PERSON_FIELDS = (
    "name", "givenName", "familyName", "alternateName",
    "jobTitle", "affiliation", "worksFor", "memberOf",
    "alumniOf", "knowsAbout",
    "birthDate", "birthPlace", "nationality", "gender",
    "address", "homeLocation", "workLocation",
    "email", "telephone",
    "sameAs", "url", "image",
    "description",
)

_ORG_FIELDS = (
    "name", "url", "logo", "description", "foundingDate",
    "address", "location", "member", "employee",
)


def _type_of(block: dict) -> str:
    t = block.get("@type", "")
    if isinstance(t, list):
        return " ".join(str(x) for x in t)
    return str(t)


def summarize(blocks: list[dict]) -> dict:
    """Resumen amigable para el LLM: extrae solo lo relevante de cada bloque."""
    summary: dict[str, list] = {"persons": [], "organizations": [], "articles": [], "other": []}

    for block in blocks:
        if not isinstance(block, dict):
            continue
        t = _type_of(block)
        if "Person" in t or "Researcher" in t:
            summary["persons"].append({k: block[k] for k in _PERSON_FIELDS if k in block})
        elif any(x in t for x in ("Organization", "University", "CollegeOrUniversity",
                                  "EducationalOrganization", "Corporation")):
            summary["organizations"].append({k: block[k] for k in _ORG_FIELDS if k in block})
        elif any(x in t for x in ("Article", "NewsArticle", "ScholarlyArticle",
                                  "BlogPosting")):
            summary["articles"].append({
                k: block[k]
                for k in ("headline", "author", "datePublished", "dateModified",
                          "description", "url", "publisher", "about")
                if k in block
            })
        elif t == "OpenGraph":
            # OG va aparte; solo lo guardamos si trae algo útil
            relevant = {k: v for k, v in block.items()
                        if k in ("og:title", "og:description", "og:type",
                                 "og:site_name", "article:author",
                                 "article:published_time", "profile:first_name",
                                 "profile:last_name", "profile:username")}
            if relevant:
                summary["other"].append({"og": relevant})

    # Limpia categorías vacías
    return {k: v for k, v in summary.items() if v}


def fetch_structured_from_url(url: str, timeout: int = 12) -> dict:
    """One-shot: descarga la URL y devuelve un resumen de su datos estructurados."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error descargando %s para extraer estructurados: %s", url, exc)
        return {}
    ct = resp.headers.get("Content-Type", "").lower()
    if "html" not in ct and "xml" not in ct:
        return {}
    blocks = extract_structured(resp.text)
    return summarize(blocks)
