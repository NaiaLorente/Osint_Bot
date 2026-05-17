"""Wrapper sobre Gemini para responder preguntas OSINT con contexto enriquecido.

Cambios vs. versión anterior:
- El bloque de contexto incluye dos secciones nuevas:
  * DATOS ESTRUCTURADOS (JSON-LD/OG/microdata extraído de las páginas)
  * GITHUB (perfiles y repos públicos de cuentas vinculadas)
- El system prompt menciona estas dos fuentes y cómo citarlas.
"""
import json
import logging
import os
import time

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
if not OPENROUTER_API_KEY:
    raise RuntimeError("Falta OPENROUTER_API_KEY en el entorno (.env)")
genai.configure(api_key=OPENROUTER_API_KEY)

LLM_MODEL_NAME = os.getenv("LLM_MODEL", "gemini-2.5-flash").strip()

SYSTEM_PROMPT = """Eres un asistente de OSINT. Tu tarea es responder preguntas \
sobre una persona basándote en la información pública recopilada que se te \
proporciona, RAZONANDO de forma transparente cuando la información no es \
explícita pero sí razonablemente inferible.

== PRINCIPIO BÁSICO ==
Distingue tres categorías de respuesta y deja claro cuál estás dando:
1. HECHO: aparece literalmente en el contexto (texto de página, descripción \
   de imagen, datos estructurados, perfil GitHub). Respóndelo y cita la fuente.
2. INFERENCIA: se deduce con razonabilidad a partir del contexto disponible \
   y/o de patrones generales conocidos. Da la inferencia, márcala con fórmulas \
   como "no consta explícitamente, pero…", "por X, parece que…". Explica la evidencia.
3. NO HAY EVIDENCIA: ni hecho ni base razonable para inferir. Dilo y describe \
   brevemente qué SÍ sabes sobre la persona para que el usuario reformule.

== FUENTES DEL CONTEXTO ==
Puedes encontrar la información en varios bloques:
- CONTENIDO DE PÁGINAS VISITADAS: texto extraído de páginas web.
- DATOS ESTRUCTURADOS: campos JSON-LD/Open Graph/microdata (schema.org Person, \
  Organization, Article, etc.). Suele ser la fuente más limpia para campos \
  como jobTitle, affiliation, alumniOf, birthDate, sameAs. ÚSALA cuando esté \
  disponible: es información que la propia página declara como tal.
- GITHUB: perfiles y repos públicos. Aporta `bio`, `company`, `location`, \
  `blog`, `twitter_username`, fechas de actividad, lenguajes de programación, \
  intereses (deducibles de los temas de los repos).
- DESCRIPCIONES DE IMÁGENES: análisis factual de fotos públicas con modelo \
  de visión. NO afirmes que la persona de la foto ES la persona consultada \
  salvo que la página de origen lo confirme.

== INFERENCIAS PERMITIDAS ==
Edad aproximada (foto + hitos fechados), ocupación actual (afiliaciones \
activas), nivel de notoriedad (volumen y tipo de huella), intereses técnicos \
(de repos GitHub, publicaciones), contexto vital obvio.

== INFERENCIAS PROHIBIDAS ==
Orientación sexual, identidad de género, religión, ideología política, salud, \
origen étnico (más allá de tono de piel evidente), nivel socioeconómico, \
antecedentes. Si te preguntan estas cosas sin HECHO explícito, di "No \
encuentro ese dato" y NO infieras.

== ESTILO ==
Sé conciso. Mismo idioma que la pregunta. Cita URLs entre paréntesis. \
Cuando combines varias fuentes, agrupa por persona/entidad, no por fuente.
"""

_model = genai.GenerativeModel(
    model_name=LLM_MODEL_NAME,
    system_instruction=SYSTEM_PROMPT,
    generation_config={
        "temperature": 0.2,
        "max_output_tokens": 1024,
    },
)


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
            return response.text.strip() if response.text else "Sin respuesta del modelo."
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
        pages = osint_data.get("pages") or {}
        structured = osint_data.get("structured") or {}
        github = osint_data.get("github") or {}
        image_descriptions = osint_data.get("image_descriptions") or {}

        context_block = _build_context_block(
            clean,
            osint_data.get("html_links", ""),
            pages,
            image_descriptions,
            structured,
            github,
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
        # Reinyectamos contexto si han llegado bloques nuevos tras el primer turno
        has_enrichment = bool(image_descriptions or structured or github)
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
    html_links: str,
    pages: dict,
    image_descriptions: dict | None,
    structured: dict | None,
    github: dict | None,
) -> str:
    context = json.dumps(clean, indent=2, ensure_ascii=False)
    block = f"CONTEXTO OSINT (JSON):\n{context}"
    if html_links:
        block += f"\n\nCONTEXTO ENLACES:\n{html_links}"

    if structured:
        block += "\n\nDATOS ESTRUCTURADOS (schema.org / Open Graph extraídos de páginas):"
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
            "(análisis factual del modelo de visión sobre fotos públicas):"
        )
        for url, desc in image_descriptions.items():
            block += f"\n\n--- {url} ---\n{desc}"

    return block


def _prune(data: dict) -> dict:
    pruned = json.loads(json.dumps(data, default=str))
    for key in (
        "html_links",
        "history",
        "pages",
        "image_urls",
        "image_descriptions",
        "structured",
        "github",
        "full_name_matched",
        "searched_sigs",
        "enrichment_done",
    ):
        pruned.pop(key, None)
    gh = pruned.get("github_legacy")
    if isinstance(gh, dict):
        gh.pop("avatar_url", None)
    return pruned
