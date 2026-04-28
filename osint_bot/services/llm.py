"""Integración con OpenRouter para responder preguntas con el contexto OSINT."""

"""Es la integración con Claude """

import json
import logging
from openai import OpenAI
from config import OPENROUTER_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

_client = OpenAI(
    api_key="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",
    base_url="https://openrouter.ai/api/v1",
)

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
    clean = _prune(osint_data)
    context = json.dumps(clean, indent=2, ensure_ascii=False)

    response = _client.chat.completions.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    "Contexto OSINT recopilado (JSON):\n"
                    f"```json\n{context}\n```\n\n"
                    f"Pregunta: {question}"
                ),
            },
        ],
    )

    return response.choices[0].message.content.strip() or "Sin respuesta."


def _prune(data: dict) -> dict:
    """Elimina campos ruidosos antes de enviar al modelo."""
    pruned = json.loads(json.dumps(data, default=str))
    gh = pruned.get("github")
    if isinstance(gh, dict):
        gh.pop("avatar_url", None)
    return pruned