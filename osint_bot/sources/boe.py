"""Búsqueda en el BOE y BORME (registros oficiales españoles) vía API pública."""

import logging

import requests

logger = logging.getLogger(__name__)

_API = "https://www.boe.es/buscar/api.php"
_DOC_URL = "https://www.boe.es/diario_boe/txt.php?id={}"


def _search_doc(name: str, doc_type: str, max_results: int) -> list[dict]:
    try:
        params = {
            "q": f'"{name}"',
            "d": doc_type,
            "rows": max_results,
            "action": "search",
        }
        r = requests.get(_API, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        docs = data.get("response", {}).get("docs", [])
        results = []
        for item in docs[:max_results]:
            doc_id = item.get("id", "")
            url = item.get("url_html") or (
                _DOC_URL.format(doc_id) if doc_id else "https://www.boe.es"
            )
            results.append({
                "title": item.get("titulo") or item.get("title") or doc_id or "Sin título",
                "url": url,
                "date": str(item.get("fecha_publicacion", ""))[:10],
                "snippet": (item.get("texto") or item.get("snippet", ""))[:200],
                "source": doc_type,
            })
        return results
    except Exception as exc:
        logger.error("Error en BOE (%s): %s", doc_type, exc)
        return []


def search_boe(name: str, max_results: int = 3) -> list[dict]:
    """Busca menciones en el BOE y BORME para el nombre dado."""
    results: list[dict] = []
    for doc_type in ("BOE", "BORME"):
        results.extend(_search_doc(name, doc_type, max_results))
    return results[:max_results * 2]
