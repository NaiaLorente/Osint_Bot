"""Fetcher de contenido web: descarga URLs y extrae texto limpio para el LLM."""

import json as _json
import logging
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

# Estos dominios requieren login y redirigen a pantalla de registro; no tiene
# sentido intentar fetchearlos porque el contenido útil no es accesible.
_GATED_DOMAINS = frozenset({
    "facebook.com",
    "instagram.com",
    "tiktok.com",
})

_LOGIN_SIGNALS = frozenset({
    "sign in", "log in", "create account", "join now",
    "iniciar sesión", "regístrate",
})


def _is_gated(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        return any(host == d or host.endswith("." + d) for d in _GATED_DOMAINS)
    except Exception:
        return False


def _is_login_page(text: str) -> bool:
    """Detecta si el texto es básicamente una pantalla de login sin contenido útil."""
    sample = text.lower()[:600]
    return sum(1 for sig in _LOGIN_SIGNALS if sig in sample) >= 2 and len(text) < 800


_META_PROPS = frozenset({
    "og:title", "og:description", "og:site_name",
    "description", "twitter:description", "twitter:title",
})


def _extract_meta(soup: "BeautifulSoup") -> str:
    parts = []
    for meta in soup.find_all("meta"):
        prop = meta.get("property") or meta.get("name", "")
        content = (meta.get("content") or "").strip()
        if content and prop in _META_PROPS:
            parts.append(f"{prop}: {content}")
    return "\n".join(parts)


_JSON_LD_TYPES = ("Person", "ProfilePage", "Organization")
_JSON_LD_FIELDS = ("name", "jobTitle", "description", "alumniOf", "worksFor", "address", "url", "location")


def _extract_json_ld(soup: "BeautifulSoup") -> str:
    """Extrae datos estructurados Schema.org de etiquetas <script type='application/ld+json'>."""
    parts = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = _json.loads(tag.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                schema_type = str(item.get("@type", ""))
                if not any(t in schema_type for t in _JSON_LD_TYPES):
                    continue
                fields: dict[str, str] = {}
                for key in _JSON_LD_FIELDS:
                    val = item.get(key)
                    if val is None:
                        continue
                    if isinstance(val, dict):
                        val = val.get("name") or val.get("@id", "")
                    elif isinstance(val, list):
                        val = ", ".join(
                            v.get("name", "") if isinstance(v, dict) else str(v)
                            for v in val[:3]
                        )
                    if val:
                        fields[key] = str(val)
                if fields:
                    lines = [f"[JSON-LD {schema_type}]"] + [f"  {k}: {v}" for k, v in fields.items()]
                    parts.append("\n".join(lines))
        except Exception:
            pass
    return "\n".join(parts)


def fetch_page_text(url: str, max_chars: int = 4000) -> str:
    """Devuelve texto limpio de una URL. Cadena vacía si falla o no hay contenido útil."""
    if _is_gated(url):
        logger.debug("Dominio bloqueado, omitiendo: %s", url)
        return ""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=8, allow_redirects=True)
        resp.raise_for_status()
        if "text/html" not in resp.headers.get("Content-Type", ""):
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")
        meta_text = _extract_meta(soup)
        json_ld_text = _extract_json_ld(soup)

        for tag in soup(["script", "style", "nav", "footer", "aside", "header"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s{2,}", " ", text)

        prefix_parts = [p for p in (json_ld_text, meta_text) if p]
        prefix = "\n\n".join(prefix_parts)

        if _is_login_page(text):
            logger.debug("Pantalla de login detectada, omitiendo: %s", url)
            return prefix  # al menos devolver datos estructurados y meta tags

        full = (prefix + "\n\n" + text) if prefix else text
        return full[:max_chars]
    except Exception as exc:
        logger.warning("Error al fetchar %s: %s", url, exc)
        return ""
