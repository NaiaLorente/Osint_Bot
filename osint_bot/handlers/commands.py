"""Command handlers: /start, /help, /search, /ask, /clear."""

import asyncio
import html
import logging
import re

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from config import ALLOWED_USER_IDS
from services.llm import answer_question
from services.osint import fetch_top_pages, format_results, run_full_search, targeted_search
from sources.fetcher import fetch_page_text
from storage.sessions import clear_session, get_session, set_session

_URL_RE = re.compile(r"https?://\S+")
_NO_ANSWER_SIGNALS = (
    "no encuentro ese dato",
    "no tengo esa información",
    "no hay información",
    "no dispongo de",
    "no se menciona",
    "no aparece",
)

logger = logging.getLogger(__name__)


def _is_no_answer(text: str) -> bool:
    lower = text.lower()
    return any(s in lower for s in _NO_ANSWER_SIGNALS)

WELCOME = (
    "<b>Bot OSINT — Información pública</b>\n\n"
    "Hago una búsqueda web para un nombre o usuario y devuelvo los primeros enlaces "
    "ordenados por relevancia, noticias recientes y perfiles en LinkedIn/X.\n"
    "Si hay credenciales de Google Search configuradas usa Google; si no, cae a DuckDuckGo.\n\n"
    "<b>Comandos</b>\n"
    "/search &lt;nombre o usuario&gt; — Buscar\n"
    "/ask &lt;pregunta&gt; — Preguntar sobre la última búsqueda\n"
    "/clear — Borrar los datos de la sesión actual\n"
    "/help — Ayuda\n\n"
    "También puedes enviarme directamente un nombre (hará una búsqueda) "
    "o una pregunta con signo de interrogación (responderá sobre la última búsqueda).\n\n"
    "<i>Solo información pública. Uso responsable. Respeta la privacidad y "
    "las leyes aplicables (RGPD/LOPDGDD).</i>"
)


def _authorized(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return update.effective_user and update.effective_user.id in ALLOWED_USER_IDS


async def _deny(update: Update) -> None:
    await update.message.reply_text("No estás autorizado a usar este bot.")


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
    await update.message.reply_chat_action(ChatAction.TYPING)
    status = await update.message.reply_text(
        f"Buscando <b>{html.escape(query)}</b>…", parse_mode=ParseMode.HTML
    )
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
        await status.edit_text(f"Error durante la búsqueda: {exc}")


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

    await update.message.reply_chat_action(ChatAction.TYPING)
    status = await update.message.reply_text("Leyendo páginas y pensando…")
    try:
        loop = asyncio.get_event_loop()

        # Primer /ask de la sesión: fetcha los top 3 resultados web para enriquecer contexto
        if session.get("pages") is None:
            session["pages"] = await fetch_top_pages(session)
            set_session(update.effective_chat.id, session)

        # Si el usuario pegó una URL en la pregunta, también la fetcha
        urls_in_question = _URL_RE.findall(question)
        if urls_in_question:
            pages = session["pages"]
            extra = await asyncio.gather(
                *[
                    loop.run_in_executor(None, fetch_page_text, url)
                    for url in urls_in_question[:3]
                    if url not in pages
                ]
            )
            for url, text in zip(urls_in_question[:3], extra):
                if isinstance(text, str) and text:
                    pages[url] = text
            set_session(update.effective_chat.id, session)

        answer = answer_question(session, question)

        note = ""
        # Si el LLM no encontró el dato, lanzar búsqueda dirigida y reintentar
        if _is_no_answer(answer):
            person = session.get("query", "")
            if person:
                await status.edit_text("Buscando más fuentes…")
                new_pages = await targeted_search(person, question, session.get("pages") or {})
                if new_pages:
                    session.setdefault("pages", {}).update(new_pages)
                    set_session(update.effective_chat.id, session)
                    answer = answer_question(session, question)
                    note = (
                        "Esta información no se encontraba en los enlaces previos "
                        "proporcionados; se ha realizado una nueva búsqueda.\n\n"
                    )

        history = session.get("history") or []
        history.append({"user": question, "assistant": answer})
        session["history"] = history
        set_session(update.effective_chat.id, session)
        await status.edit_text(f"{note}{answer}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error en Q&A")
        await status.edit_text(f"Error al responder: {exc}")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    clear_session(update.effective_chat.id)
    await update.message.reply_text("Sesión borrada.")


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
