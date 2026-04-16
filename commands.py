"""Command handlers: /start, /help, /search, /ask, /clear."""
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import ALLOWED_USER_IDS
from services.osint import run_full_search, format_results
from services.llm import answer_question
from storage.sessions import get_session, set_session, clear_session

logger = logging.getLogger(__name__)

WELCOME = (
    "👋 <b>Bot OSINT — Información pública</b>\n\n"
    "Busco información pública sobre una persona en fuentes abiertas: "
    "Wikipedia, GitHub, LinkedIn (enlace), X/Twitter, noticias y web general.\n\n"
    "<b>Comandos</b>\n"
    "/search &lt;nombre o usuario&gt; — Buscar\n"
    "/ask &lt;pregunta&gt; — Preguntar sobre la última búsqueda\n"
    "/clear — Borrar los datos de la sesión actual\n"
    "/help — Ayuda\n\n"
    "También puedes enviarme directamente un nombre (hará una búsqueda) "
    "o una pregunta con signo de interrogación (responderá sobre la última búsqueda).\n\n"
    "⚠️ <i>Solo información pública. Uso responsable. Respeta la privacidad y "
    "las leyes aplicables (RGPD/LOPDGDD).</i>"
)


def _authorized(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return update.effective_user and update.effective_user.id in ALLOWED_USER_IDS


async def _deny(update: Update) -> None:
    await update.message.reply_text("⛔ No estás autorizado a usar este bot.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Uso: /search <nombre o usuario>")
        return
    await perform_search(update, query)


async def perform_search(update: Update, query: str) -> None:
    status = await update.message.reply_text(f"🔎 Buscando <b>{query}</b>…", parse_mode=ParseMode.HTML)
    try:
        results = await run_full_search(query)
        set_session(update.effective_chat.id, results)
        body = format_results(results)
        for chunk in _chunk_text(body, 3800):
            await update.message.reply_text(
                chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        await status.delete()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error en búsqueda")
        await status.edit_text(f"❌ Error durante la búsqueda: {exc}")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    question = " ".join(context.args).strip()
    if not question:
        await update.message.reply_text("Uso: /ask <pregunta>")
        return
    await perform_question(update, question)


async def perform_question(update: Update, question: str) -> None:
    session = get_session(update.effective_chat.id)
    if not session:
        await update.message.reply_text(
            "No hay datos en sesión. Primero haz una búsqueda con /search <nombre>."
        )
        return
    status = await update.message.reply_text("🧠 Pensando…")
    try:
        answer = answer_question(session, question)
        await status.edit_text(answer)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error en Q&A")
        await status.edit_text(f"❌ Error al responder: {exc}")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    clear_session(update.effective_chat.id)
    await update.message.reply_text("🗑️ Sesión borrada.")


def _chunk_text(text: str, size: int) -> list[str]:
    """Divide `text` en trozos ≤ size respetando saltos de línea."""
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > size:
            if current:
                chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks
