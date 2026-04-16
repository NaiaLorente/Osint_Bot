"""Integración con Claude para responder preguntas con el contexto OSINT."""
import json
import logging

from anthropic import Anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

_client = Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Eres un asistente de OSINT. Tu tarea es responder preguntas \
sobre una persona basándote ÚNICAMENTE en la información pública recopilada \
que te proporciona el usuario en el contexto.

Reglas estrictas:
- Responde solo con datos que aparezcan explícitamente en el contexto.
- Si el contexto no contiene la información necesaria para responder, di \
  claramente: "No encuentro ese dato en las fuentes recopiladas."
- No inventes datos, no deduzcas información personal sensible, no hagas \
  suposiciones sobre ideología, salud, orientación, etc.
- Cuando sea útil, menciona la fuente entre paréntesis (p. ej. "según \
  Wikipedia", "según su perfil de GitHub").
- Sé conciso. Responde en el mismo idioma que la pregunta.
- Si la pregunta pide datos sensibles (direcciones exactas, teléfonos, \
  DNI, datos familiares de menores...), recházala y explica por qué.
"""


def answer_question(osint_data: dict, question: str) -> str:
    """Responde una pregunta usando los datos OSINT como contexto."""
    # Serializamos limpiando avatar_url (ruido para el modelo).
    clean = _prune(osint_data)
    context = json.dumps(clean, indent=2, ensure_ascii=False)

    message = _client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Contexto OSINT recopilado (JSON):\n"
                    f"```json\n{context}\n```\n\n"
                    f"Pregunta: {question}"
                ),
            }
        ],
    )

    # message.content es una lista de bloques; tomamos el texto.
    text_parts = [
        block.text for block in message.content if getattr(block, "type", "") == "text"
    ]
    return "\n".join(text_parts).strip() or "Sin respuesta."


def _prune(data: dict) -> dict:
    """Elimina campos ruidosos antes de enviar al modelo."""
    pruned = json.loads(json.dumps(data, default=str))  # copia profunda
    gh = pruned.get("github")
    if isinstance(gh, dict):
        gh.pop("avatar_url", None)
    return pruned
