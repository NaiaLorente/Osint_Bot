"""Análisis de imágenes con Gemini, con rate limit y retry para plan free.

Cambios vs. versión anterior:
- Concurrency=1 por defecto: serializa para no quemar RPM en ráfagas.
- Rate limit global: respeta VISION_RPM (5 por defecto, configurable).
- Retry con backoff exponencial cuando Gemini devuelve 429.
- Modelo por defecto: gemini-2.5-flash-lite. Tiene su propio cupo separado
  del que usa services/llm.py (gemini-2.5-flash), así las llamadas de visión
  NO compiten con las de texto. Cambiable con la env var VISION_MODEL.

Archivo destinado a: services/vision.py
"""
import asyncio
import logging
import os
import time

import google.generativeai as genai

from sources.images import fetch_image_bytes

logger = logging.getLogger(__name__)

# Configurable por entorno.
_VISION_MODEL_NAME = os.getenv("VISION_MODEL", "gemini-2.5-flash-lite").strip()
try:
    _VISION_RPM = max(1, int(os.getenv("VISION_RPM", "5")))
except ValueError:
    _VISION_RPM = 5
_MIN_INTERVAL = 60.0 / _VISION_RPM  # segundos mínimos entre llamadas

_PROMPT = """Describe esta imagen de forma factual y concisa.

Si aparece una persona, incluye SOLO lo VISIBLE:
- sexo aparente y rango de edad aproximado
- color y largo del pelo; color de ojos si se aprecia
- complexión, altura aparente si hay referencia
- vestimenta y accesorios (gafas, joyas, sombrero, etc.)
- contexto: foto de perfil, foto de evento, retrato, grupo, exterior/interior
- texto visible en la imagen (carteles, ropa con texto, etc.)

Reglas estrictas:
- NO identifiques a la persona por nombre, aunque creas reconocerla.
- NO inventes datos no visibles. Si algo no se ve, OMÍTELO.
- NO emitas juicios estéticos.
- Si es un logo, icono, gráfico, captura de pantalla sin personas o imagen \
  irrelevante, dilo en una frase y para.
- Máximo 4 frases.
"""

_vision_model = genai.GenerativeModel(
    model_name=_VISION_MODEL_NAME,
    generation_config={
        "temperature": 0.2,
        "max_output_tokens": 256,
    },
)

# --- Rate limiter global (un token bucket simple para todo el proceso) ---
_last_call: float = 0.0
_rate_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """Crea el lock perezosamente para asociarlo al event loop activo."""
    global _rate_lock
    if _rate_lock is None:
        _rate_lock = asyncio.Lock()
    return _rate_lock


async def _wait_turn() -> None:
    """Bloquea hasta que respetemos _MIN_INTERVAL desde la última llamada."""
    global _last_call
    async with _get_lock():
        now = time.monotonic()
        elapsed = now - _last_call
        if elapsed < _MIN_INTERVAL:
            await asyncio.sleep(_MIN_INTERVAL - elapsed)
        _last_call = time.monotonic()


# --- Llamada al modelo + retry ---

def _generate_blocking(img_bytes: bytes, mime: str, alt: str) -> str | None:
    parts: list = [_PROMPT]
    if alt:
        parts.append(f"Texto alternativo de la página de origen: «{alt}»")
    parts.append({"mime_type": mime, "data": img_bytes})
    resp = _vision_model.generate_content(parts)
    return (resp.text or "").strip() if hasattr(resp, "text") and resp.text else None


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in (
        "429", "quota", "rate limit", "rate_limit",
        "resource_exhausted", "exceeded",
    ))


async def _describe_with_retry(url: str, alt: str, max_attempts: int = 4) -> str | None:
    loop = asyncio.get_event_loop()
    fetched = await loop.run_in_executor(None, fetch_image_bytes, url)
    if not fetched:
        return None
    img_bytes, mime = fetched

    for attempt in range(max_attempts):
        await _wait_turn()
        try:
            return await loop.run_in_executor(
                None, _generate_blocking, img_bytes, mime, alt
            )
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit_error(exc) and attempt < max_attempts - 1:
                # 30s, 60s, 120s. Suficiente para que el cupo por minuto reabra.
                wait = 30 * (2 ** attempt)
                logger.warning(
                    "Rate limit en visión, esperando %ds (intento %d/%d): %s",
                    wait, attempt + 1, max_attempts, exc,
                )
                await asyncio.sleep(wait)
                continue
            logger.warning("Error analizando %s: %s", url, exc)
            return None
    return None


async def describe_images(
    images: list[dict],
    concurrency: int = 1,
) -> dict[str, str]:
    """Describe varias imágenes. Devuelve {url: descripción}.

    concurrency=1 por defecto para no rebasar el cupo de RPM en plan free.
    Si subes a Tier 1 / pago, puedes pasar concurrency=4 desde el caller.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(img: dict) -> tuple[str, str | None]:
        url = img.get("url") or ""
        alt = img.get("alt") or ""
        if not url:
            return ("", None)
        async with sem:
            desc = await _describe_with_retry(url, alt)
        return (url, desc)

    pairs = await asyncio.gather(*[_one(i) for i in images])
    return {url: desc for url, desc in pairs if url and desc}
