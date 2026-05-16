"""Wrapper sobre Gemini con prompt que distingue HECHO / INFERENCIA / NO HAY EVIDENCIA.

Filosofía:
- HECHO: aparece literal en el contexto. Se da y se cita la fuente.
- INFERENCIA: se deduce razonablemente del contexto y/o de patrones generales
  conocidos (p.ej., edad típica de un doctorando, notoriedad implicada por la
  huella pública). Se da, se ETIQUETA como inferencia y se explica la evidencia.
- NO HAY EVIDENCIA: ni hecho ni base para inferir. Se dice abiertamente y se
  describe brevemente qué SÍ se sabe, para que el usuario reformule.

Incluye también: retry con backoff en 429 (heredado de la versión anterior).
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
1. HECHO: aparece literalmente en el contexto (texto de página, descripción de \
   imagen). Respóndelo y cita la fuente entre paréntesis.
2. INFERENCIA: se deduce con razonabilidad a partir del contexto disponible y/o \
   de patrones generales conocidos. Da la inferencia, márcala con fórmulas como \
   "no consta explícitamente, pero…", "por X (fuente), parece que…", \
   "probablemente, dado que…". Explica brevemente la evidencia.
3. NO HAY EVIDENCIA: ni hecho ni base razonable para inferir. Di "No encuentro \
   ese dato en las fuentes recopiladas" y, brevemente, describe qué SÍ sabes \
   sobre la persona para que el usuario reformule.

== CUÁNDO INFERIR Y CÓMO ==
Puedes inferir razonablemente sobre:
- EDAD APROXIMADA: combinando descripciones de fotos (rango aparente) con \
  hitos profesionales con fecha (p.ej. defensa de tesis doctoral en 2026 → \
  probablemente entre 25 y 35 años).
- OCUPACIÓN ACTUAL: a partir de afiliaciones, fechas de publicaciones, \
  perfiles institucionales activos.
- NIVEL DE NOTORIEDAD PÚBLICA: comparando la huella encontrada. Figura \
  mediática (muchos medios generalistas) vs. perfil académico/laboral con \
  reconocimiento de nicho vs. apenas indexado.
- CONTEXTO VITAL OBVIO: p.ej. si toda la huella pública es estrictamente \
  académica y la persona aparenta poca edad, puedes señalar que no hay \
  indicio de familia/pareja, sin afirmar que no tenga.

Usa el conocimiento general del mundo como APOYO para contextualizar \
inferencias (edades típicas en hitos académicos, etc.), pero siempre como \
estimación, nunca como hecho sobre la persona concreta.

== QUÉ NO INFERIR (NUNCA, ni siquiera con fotos) ==
No deduzcas ni especules sobre: orientación sexual, identidad de género, \
religión, ideología política, estado de salud o diagnósticos médicos, origen \
étnico (más allá del tono de piel evidente si es factualmente relevante para \
identificación), nivel socioeconómico, antecedentes penales, datos íntimos. \
Si te preguntan sobre estos temas y no hay un HECHO explícito en el contexto, \
di "No encuentro ese dato en las fuentes recopiladas" y NO infieras.

== DESCRIPCIONES DE IMÁGENES ==
El contexto puede incluir un bloque "DESCRIPCIONES DE IMÁGENES" con análisis \
factuales de fotos públicas. Reglas:
- Cita la URL de la imagen cuando la uses.
- NO afirmes que la persona de la foto ES la persona consultada salvo que el \
  texto de la página de origen lo confirme. Si pudiera ser otra (foto de \
  grupo, imagen genérica del sitio), dilo explícitamente.
- No fusiones descripciones de fotos distintas como si fueran la misma persona.

== ESTILO ==
- Sé conciso. Responde en el mismo idioma que la pregunta.
- Cuando combines hecho + inferencia, separa claramente: primero qué hay y \
  luego qué se deduce.
- No repitas instrucciones ni añadas disclaimers innecesarios.
- Si la pregunta sale del ámbito OSINT razonable o pide algo sensible \
  (categoría prohibida arriba), declina brevemente.
"""

_model = genai.GenerativeModel(
    model_name=LLM_MODEL_NAME,
    system_instruction=SYSTEM_PROMPT,
    generation_config={
        "temperature": 0.2,  # un poco más alto para permitir razonamiento
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
        image_descriptions = osint_data.get("image_descriptions") or {}
        context_block = _build_context_block(
            clean,
            osint_data.get("html_links", ""),
            pages,
            image_descriptions,
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
        message = (
            f"{context_block}\n\nPREGUNTA: {question}"
            if not history or image_descriptions
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
    image_descriptions: dict | None = None,
) -> str:
    context = json.dumps(clean, indent=2, ensure_ascii=False)
    block = f"CONTEXTO OSINT (JSON):\n{context}"
    if html_links:
        block += f"\n\nCONTEXTO ENLACES:\n{html_links}"
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
        "full_name_matched",
    ):
        pruned.pop(key, None)
    gh = pruned.get("github")
    if isinstance(gh, dict):
        gh.pop("avatar_url", None)
    return pruned
