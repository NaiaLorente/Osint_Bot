"""Handler de mensajes libres (sin comando).

Heurística: si hay sesión activa y el texto parece una pregunta,
se trata como /ask. En caso contrario se trata como /search.
"""
from telegram import Update
from telegram.ext import ContextTypes

from config import ALLOWED_USER_IDS
from handlers.commands import perform_search, perform_question

_QUESTION_STARTS = (
    "qué", "que ", "quién", "quien ", "cuándo", "cuando ",
    "dónde", "donde ", "cómo", "como ", "por qué", "porque ",
    "cuál", "cual ", "cuántos", "cuantos ", "cuántas", "cuantas ",
    "dime", "explica", "resume", "cuenta", "sabes",
    "what", "who", "when", "where", "why", "how", "which",
)


def _looks_like_question(text: str) -> bool:
    t = text.lower().strip()
    if not t:
        return False
    if t.endswith("?") or "¿" in t:
        return True
    return any(t.startswith(w) for w in _QUESTION_STARTS)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if ALLOWED_USER_IDS and (
        not update.effective_user or update.effective_user.id not in ALLOWED_USER_IDS
    ):
        await update.message.reply_text("⛔ No estás autorizado a usar este bot.")
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    # Importación tardía para evitar ciclos.
    from storage.sessions import get_session

    session = get_session(update.effective_chat.id)
    if session and _looks_like_question(text):
        await perform_question(update, text)
    else:
        await perform_search(update, text)
