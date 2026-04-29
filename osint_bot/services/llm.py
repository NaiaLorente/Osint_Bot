
import json
import logging
import google.generativeai as genai
import os
from dotenv import load_dotenv

# Cargamos las variables del .env
load_dotenv()

logger = logging.getLogger(__name__)

# Configuración de la API de Google
# Usamos la clave que ya tienes en tu .env
GEMINI_API_KEY = os.getenv("OPENROUTER_API_KEY") # Tu clave AIza...
genai.configure(api_key=GEMINI_API_KEY)

# Configuramos el modelo gratuito
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash-lite",
    generation_config={
        "temperature": 0.1, # Menos creatividad, más precisión para OSINT
        "max_output_tokens": 1024,
    }
)

SYSTEM_PROMPT = """Eres un asistente de OSINT. Tu tarea es responder preguntas \
sobre una persona basándote ÚNICAMENTE en la información pública recopilada \
que te proporciona el usuario en el contexto.
Reglas estrictas:
- Responde solo con datos que aparezcan explícitamente en el contexto.
- Si el contexto no contiene la información necesaria para responder, di \
  claramente: "No encuentro ese dato en las fuentes recopiladas."
- No inventes datos, no deduzcas información personal sensible.
- Menciona la fuente entre paréntesis cuando esté disponible.
- Sé conciso. Responde en el mismo idioma que la pregunta.
"""

def answer_question(osint_data: dict, question: str) -> str:
    """Responde usando la librería nativa de Google Generative AI."""
    try:
        clean = _prune(osint_data)
        context = json.dumps(clean, indent=2, ensure_ascii=False)
        
        # Unimos el prompt del sistema con la pregunta y el contexto
        full_prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"CONTEXTO OSINT (JSON):\n{context}\n\n"
            f"PREGUNTA DEL USUARIO: {question}"
        )
        
        response = model.generate_content(full_prompt)
        
        if response.text:
            return response.text.strip()
        return "Sin respuesta del modelo."

    except Exception as e:
        logger.error(f"Error crítico en Gemini: {e}")
        return f"Error al procesar la consulta: {str(e)}"

def _prune(data: dict) -> dict:
    """Elimina campos ruidosos antes de enviar al modelo."""
    # Creamos una copia para no modificar el original
    pruned = json.loads(json.dumps(data, default=str))
    gh = pruned.get("github")
    if isinstance(gh, dict):
        gh.pop("avatar_url", None)
    return pruned