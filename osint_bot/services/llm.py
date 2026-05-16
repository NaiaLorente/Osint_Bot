import json
import logging
import os

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
if not OPENROUTER_API_KEY:
    raise RuntimeError("Falta OPENROUTER_API_KEY en el entorno (.env)")
genai.configure(api_key=OPENROUTER_API_KEY)

SYSTEM_PROMPT = """Eres un asistente de OSINT. Tu tarea es responder preguntas \
sobre una persona basándote ÚNICAMENTE en la información pública recopilada \
que te proporciona el usuario en el contexto.
Reglas estrictas:
- Responde solo con datos que aparezcan explícitamente en el contexto.
- Si el contexto no contiene la información necesaria para responder, di \
  claramente: "No encuentro ese dato en las fuentes recopiladas."
- No inventes datos, no deduzcas información personal sensible.
- Menciona la fuente entre paréntesis cuando esté disponible.
- Si la información solicitada ya está en los enlaces previos proporcionados, responde directamente sin decir que hiciste una nueva búsqueda.
- No agregues explicaciones innecesarias ni repitas instrucciones.
- Sé conciso. Responde en el mismo idioma que la pregunta.
"""

_model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    system_instruction=SYSTEM_PROMPT,
    generation_config={
        "temperature": 0.1,
        "max_output_tokens": 1024,
    },
)


def answer_question(osint_data: dict, question: str) -> str:
    """Responde usando el Chat API de Gemini con historial multi-turno nativo."""
    try:
        clean = _prune(osint_data)
        pages = osint_data.get("pages") or {}
        context_block = _build_context_block(clean, osint_data.get("html_links", ""), pages)
        history = osint_data.get("history") or []

        # Convertir historial al formato nativo de Gemini.
        # El contexto OSINT se inyecta una sola vez en el primer mensaje
        # para no repetirlo en cada turno.
        gemini_history = []
        for i, turn in enumerate(history):
            user_msg = turn.get("user", "")
            if i == 0:
                user_msg = f"{context_block}\n\nPREGUNTA: {user_msg}"
            gemini_history.append({"role": "user", "parts": [user_msg]})
            gemini_history.append({"role": "model", "parts": [turn.get("assistant", "")]})

        chat = _model.start_chat(history=gemini_history)

        # Si no hay historial previo, incluir el contexto en este primer mensaje
        message = f"{context_block}\n\nPREGUNTA: {question}" if not history else question
        response = chat.send_message(message)

        return response.text.strip() if response.text else "Sin respuesta del modelo."

    except Exception as exc:
        logger.error("Error en Gemini: %s", exc)
        return f"Error al procesar la consulta: {exc}"


def _build_context_block(clean: dict, html_links: str, pages: dict) -> str:
    context = json.dumps(clean, indent=2, ensure_ascii=False)
    block = f"CONTEXTO OSINT (JSON):\n{context}"
    if html_links:
        block += f"\n\nCONTEXTO ENLACES:\n{html_links}"
    if pages:
        block += "\n\nCONTENIDO DE PÁGINAS VISITADAS:"
        for url, text in pages.items():
            block += f"\n\n--- {url} ---\n{text}"
    return block


def _prune(data: dict) -> dict:
    """Elimina campos ruidosos antes de enviar al modelo."""
    pruned = json.loads(json.dumps(data, default=str))
    pruned.pop("html_links", None)
    pruned.pop("history", None)
    pruned.pop("pages", None)  # se pasa aparte en _build_context_block
    gh = pruned.get("github")
    if isinstance(gh, dict):
        gh.pop("avatar_url", None)
    return pruned
