"""Wrapper sobre Gemini con contexto enriquecido por múltiples fuentes.

Bloques del contexto pasados al LLM (en este orden):
  1. CONTEXTO OSINT (JSON) — metadatos limpios
  2. CONTEXTO ENLACES — lista HTML de las URLs top
  3. WIKIDATA — datos biográficos estructurados (cuando existen)
  4. WIKIPEDIA — resumen biográfico (cuando existe)
  5. DATOS ESTRUCTURADOS — schema.org/JSON-LD/OG de las páginas visitadas
  6. GITHUB — perfiles y repos públicos
  7. CONTENIDO DE PÁGINAS VISITADAS — texto extraído
  8. DESCRIPCIONES DE IMÁGENES — análisis de visión sobre fotos públicas
"""
import json
import logging
import re
import time

import google.generativeai as genai

from config import GEMINI_API_KEY, LLM_MODEL_NAME

logger = logging.getLogger(__name__)
genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """Eres un asistente de OSINT. Tu tarea es responder preguntas \
sobre una persona basándote en la información pública recopilada que se te \
proporciona, RAZONANDO de forma transparente cuando la información no es \
explícita pero sí razonablemente inferible.

== PRINCIPIO BÁSICO ==
Distingue tres categorías y deja claro cuál estás dando:
1. HECHO: aparece literal en el contexto. Cita la fuente.
2. INFERENCIA: se deduce con razonabilidad de hechos y patrones generales. \
   Márcalo: "no consta explícitamente, pero…", "por X parece que…". Explica \
   la evidencia.
3. NO HAY EVIDENCIA: ni hecho ni base para inferir. Dilo y describe brevemente \
   qué sí sabes para que el usuario reformule.

== ORDEN DE PREFERENCIA DE FUENTES ==
Prioriza, en este orden, lo más fiable cuando varias fuentes coinciden:
- WIKIDATA (datos estructurados verificados por la comunidad). Si Wikidata da \
  fecha de nacimiento, ocupación, empleador, etc., es HECHO de alta confianza.
- WIKIPEDIA (resumen biográfico curado).
- DATOS ESTRUCTURADOS de páginas (JSON-LD schema.org de la propia institución/medio).
- GITHUB (datos declarados por el usuario).
- Contenido de páginas (texto plano).
- Descripciones de imágenes (factual pero parcial).

Si Wikidata dice una cosa y una página comercial dice otra, prefiere Wikidata \
y menciona la discrepancia.

== INFERENCIAS PERMITIDAS ==
Edad aproximada (foto + hitos fechados), ocupación actual, nivel de notoriedad, \
intereses técnicos (repos GitHub, publicaciones), contexto vital obvio.

== INFERENCIAS PROHIBIDAS ==
Orientación sexual, identidad de género, religión, ideología política, salud, \
origen étnico (más allá de tono de piel evidente), nivel socioeconómico, \
antecedentes. Si te preguntan estas cosas sin HECHO explícito, di "No \
encuentro ese dato" y NO infieras.

== IMÁGENES ==
NO afirmes que la persona de la foto ES la persona consultada salvo que el \
texto de la página de origen lo confirme. No fusiones descripciones de fotos \
distintas como si fueran la misma persona.

== ESTILO ==
Conciso. Mismo idioma que la pregunta. Cita URLs entre paréntesis. Agrupa \
por persona/entidad, no por fuente. Responde en párrafos breves y evita \
listas, viñetas, negritas y asteriscos. Si presentas hechos o inferencias, hazlo \
en oraciones normales, sin encabezados de sección.
"""

_model = genai.GenerativeModel(
    model_name=LLM_MODEL_NAME,
    system_instruction=SYSTEM_PROMPT,
    generation_config={
        "temperature": 0.2,
        "max_output_tokens": 1024,
    },
)


def _strip_response_label(text: str) -> str:
    text = re.sub(
        r'^\s*\*{0,2}(HECHO|INFERENCIA|NO HAY EVIDENCIA)\*{0,2}\s*:\s*',
        '',
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    ).strip()
    return _normalize_response_text(text)


def _normalize_response_text(text: str) -> str:
    text = re.sub(r'^\s*[\*\-\u2022]\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in (
        "429", "quota", "rate limit", "rate_limit",
        "resource_exhausted", "exceeded",
    ))


def _send_with_retry(chat, message: str, max_attempts: int = 3) -> str:
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            response = chat.send_message(message)
            raw = response.text.strip() if response.text else "Sin respuesta del modelo."
            return _strip_response_label(raw)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if _is_rate_limit_error(exc) and attempt < max_attempts - 1:
                wait = 30 * (2 ** attempt)
                logger.warning(
                    "Rate limit en LLM, esperando %ds (intento %d/%d)",
                    wait, attempt + 1, max_attempts,
                )
                time.sleep(wait)
                continue
            raise
    raise last_exc or RuntimeError("LLM retry agotado")


def answer_question(osint_data: dict, question: str) -> str:
    try:
        clean = _prune(osint_data)
        context_block = _build_context_block(
            clean,
            html_links=osint_data.get("html_links", ""),
            pages=osint_data.get("pages") or {},
            image_descriptions=osint_data.get("image_descriptions") or {},
            structured=osint_data.get("structured") or {},
            github=osint_data.get("github") or {},
            wikipedia=osint_data.get("wikipedia"),
            wikidata=osint_data.get("wikidata"),
        )
        history = osint_data.get("history") or []

        gemini_history = []
        for i, turn in enumerate(history):
            user_msg = turn.get("user", "")
            if i == 0:
                user_msg = f"{context_block}\n\nPREGUNTA: {user_msg}"
            gemini_history.append({"role": "user", "parts": [user_msg]})
            gemini_history.append({"role": "model", "parts": [turn.get("assistant", "")]})

        chat = _model.start_chat(history=gemini_history)
        # Reinyectamos contexto si hay enriquecimiento que pudiera haberse
        # añadido tras el primer turno (vision, structured incremental, etc.)
        has_enrichment = bool(
            osint_data.get("image_descriptions")
            or osint_data.get("structured")
            or osint_data.get("github")
        )
        message = (
            f"{context_block}\n\nPREGUNTA: {question}"
            if not history or has_enrichment
            else question
        )
        return _send_with_retry(chat, message)

    except Exception as exc:
        logger.error("Error en Gemini: %s", exc)
        if _is_rate_limit_error(exc):
            return (
                "Cupo de la API agotado temporalmente. Espera ~1 minuto e "
                "intenta de nuevo. Si esto pasa a menudo, considera activar "
                "Tier 1 en Google Cloud o cambiar LLM_MODEL a "
                "gemini-2.5-flash-lite en el .env."
            )
        return f"Error al procesar la consulta: {exc}"


def _build_context_block(
    clean: dict,
    *,
    html_links: str,
    pages: dict,
    image_descriptions: dict,
    structured: dict,
    github: dict,
    wikipedia: dict | None,
    wikidata: dict | None,
) -> str:
    block = f"CONTEXTO OSINT (JSON):\n{json.dumps(clean, indent=2, ensure_ascii=False)}"

    if html_links:
        block += f"\n\nCONTEXTO ENLACES:\n{html_links}"

    if wikidata:
        block += "\n\nWIKIDATA (datos biográficos estructurados, alta confianza):\n"
        block += json.dumps(wikidata, ensure_ascii=False, indent=2)

    if wikipedia:
        block += "\n\nWIKIPEDIA:"
        block += f"\n--- {wikipedia.get('url', '')} ---"
        block += f"\nTítulo: {wikipedia.get('title', '')}"
        block += f"\nIdioma: {wikipedia.get('lang', '')}"
        block += f"\n{wikipedia.get('summary', '')}"

    if structured:
        block += "\n\nDATOS ESTRUCTURADOS (schema.org / Open Graph de páginas):"
        for url, data in structured.items():
            if not data:
                continue
            block += f"\n\n--- {url} ---\n{json.dumps(data, ensure_ascii=False, indent=2)}"

    if github:
        block += "\n\nGITHUB (perfiles y repos públicos):"
        for user, info in github.items():
            block += f"\n\n--- @{user} ---\n{json.dumps(info, ensure_ascii=False, indent=2)}"

    if pages:
        block += "\n\nCONTENIDO DE PÁGINAS VISITADAS:"
        for url, text in pages.items():
            block += f"\n\n--- {url} ---\n{text}"

    if image_descriptions:
        block += (
            "\n\nDESCRIPCIONES DE IMÁGENES "
            "(modelo de visión sobre fotos públicas):"
        )
        for url, desc in image_descriptions.items():
            block += f"\n\n--- {url} ---\n{desc}"

    return block


def _prune(data: dict) -> dict:
    """Quita campos que ya se transportan en su propia sección."""
    pruned = json.loads(json.dumps(data, default=str))
    for key in (
        "html_links",
        "history",
        "pages",
        "image_urls",
        "image_descriptions",
        "structured",
        "github",
        "wikipedia",
        "wikidata",
        "full_name_matched",
        "searched_sigs",
        "enrichment_done",
    ):
        pruned.pop(key, None)
    return pruned