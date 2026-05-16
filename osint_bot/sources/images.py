"""Extracción y descarga de imágenes desde páginas web públicas.

Pensado solo para imágenes embebidas en páginas accesibles sin autenticación.
NO intenta saltar muros de login ni descargar contenido de Instagram, LinkedIn
o Facebook directamente — esas plataformas sirven páginas casi vacías a clientes
sin sesión iniciada, y rascarlas viola sus ToS.

Archivo destinado a: sources/images.py
"""
import logging
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# URLs típicas de imágenes que NO aportan (logos, iconos, tracking, etc.)
_NOISE_URL_RE = re.compile(
    r"(logo|icon|favicon|avatar-default|placeholder|sprite|emoji|"
    r"pixel|1x1|facebook\.com/tr|google-analytics|doubleclick|gravatar|"
    r"blank\.gif|spacer\.gif|\.svg(\?|$))",
    re.IGNORECASE,
)
# Alt-texts típicos de UI, no de contenido
_NOISE_ALT_RE = re.compile(
    r"^(logo|icon|menu|search|close|arrow|share|tweet|like|prev|next)$",
    re.IGNORECASE,
)

_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB tope por imagen
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,image/*;q=0.8,*/*;q=0.5",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
}


def _is_noise(url: str, alt: str = "") -> bool:
    if _NOISE_URL_RE.search(url):
        return True
    if alt and _NOISE_ALT_RE.match(alt.strip()):
        return True
    return False


def extract_image_urls(html: str, base_url: str, max_images: int = 5) -> list[dict]:
    """Saca URLs de imágenes 'útiles' de un HTML.

    Prioriza meta-imágenes (og:image, twitter:image) — suelen ser la imagen
    principal declarada por la propia página — y luego <img> con alt útil
    o dimensiones razonables.

    Devuelve lista de dicts: {url, alt, source}.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error parseando HTML de %s: %s", base_url, exc)
        return []

    results: list[dict] = []
    seen: set[str] = set()

    # 1) Meta-imágenes (Open Graph / Twitter Card)
    for prop in ("og:image", "og:image:url", "og:image:secure_url",
                 "twitter:image", "twitter:image:src"):
        meta = (
            soup.find("meta", attrs={"property": prop})
            or soup.find("meta", attrs={"name": prop})
        )
        if not meta:
            continue
        src = (meta.get("content") or "").strip()
        if not src:
            continue
        url = urljoin(base_url, src)
        if url in seen or _is_noise(url):
            continue
        seen.add(url)
        results.append({"url": url, "alt": "", "source": "og"})

    # 2) <img> embebidas con cierta credibilidad
    for img in soup.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
        )
        if not src:
            continue
        url = urljoin(base_url, src.strip())
        alt = (img.get("alt") or "").strip()
        if url in seen or _is_noise(url, alt):
            continue

        # Filtro por dimensiones cuando están declaradas
        try:
            w = int(img.get("width") or 0)
            h = int(img.get("height") or 0)
            if w and h and (w < 100 or h < 100):
                continue
        except (ValueError, TypeError):
            pass

        seen.add(url)
        results.append({"url": url, "alt": alt, "source": "img"})
        if len(results) >= max_images:
            break

    return results[:max_images]


def fetch_page_images(url: str, max_images: int = 3, timeout: int = 12) -> list[dict]:
    """Descarga una página y extrae sus URLs de imagen relevantes."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo descargar %s para extraer imágenes: %s", url, exc)
        return []

    ct = resp.headers.get("Content-Type", "").lower()
    if "html" not in ct and "xml" not in ct:
        return []

    return extract_image_urls(resp.text, base_url=url, max_images=max_images)


def fetch_image_bytes(url: str, timeout: int = 10) -> tuple[bytes, str] | None:
    """Descarga una imagen. Devuelve (bytes, mime) o None.

    Streamea con tope de tamaño para evitar bajar archivos enormes.
    """
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout, stream=True)
        resp.raise_for_status()

        ct = resp.headers.get("Content-Type", "").lower()
        if not ct.startswith("image/"):
            return None
        mime = ct.split(";")[0].strip()

        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(chunk_size=16384):
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_IMAGE_BYTES:
                logger.warning(
                    "Imagen >%d bytes, descartada: %s", _MAX_IMAGE_BYTES, url
                )
                return None
        return b"".join(chunks), mime
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error descargando imagen %s: %s", url, exc)
        return None
