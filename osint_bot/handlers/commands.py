"""Command handlers: /start, /help, /search, /ask, /clear.

Cambios vs. versión anterior:
- _is_no_answer ahora ignora respuestas que contienen marcadores de razonamiento
  (pero, parece, probablemente, sugiere, etc.). Solo dispara búsqueda dirigida
  cuando la respuesta es PURAMENTE "no encuentro" sin razonamiento añadido.
- Esto permite que el LLM dé inferencias razonables sin que el bot interprete
  cualquier "no aparece explícitamente" como necesidad de buscar más.
"""

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
from services.vision import describe_images
from sources.fetcher import fetch_page_text
from sources.images import fetch_page_images
from storage.sessions import clear_session, get_session, set_session

_URL_RE = re.compile(r"https?://\S+")

# Señales de que el LLM se ha rendido sin aportar nada.
_NO_ANSWER_SIGNALS = (
    "no encuentro ese dato",
    "no tengo esa información",
    "no hay información",
    "no dispongo de",
    "no se menciona",
    "no aparece",
    "no consta",
)

# Si la respuesta contiene CUALQUIERA de estos marcadores, significa que el LLM
# ha dado una inferencia o aportado contexto, así que NO la tratamos como
# "respuesta vacía" aunque también contenga alguna de las señales de arriba.
_REASONING_MARKERS = (
    " pero ", " aunque ", " sin embargo", "no obstante",
    "por tanto", "por lo tanto", " parece ", "probablemente",
    " sugiere ", " indica ", " según ", " dado que",
    " por la foto", " en la imagen", " la imagen sugiere",
    " su huella", " su perfil", " su trayectoria",
    " however", " but ", " although ",
)

# Palabras que disparan análisis de imágenes
_VISUAL_RE = re.compile(
    r"\b("
    r"foto|fotos|imagen|im[aá]genes|"
    r"aspecto|apariencia|f[ií]sico|f[ií]sicamente|"
    r"pelo|cabello|melena|barba|bigote|"
    r"ojos|gafas|sonrisa|tatuaje|piercing|"
    r"altura|complexi[oó]n|alto|alta|bajo|baja|delgad[ao]|"
    r"vestimenta|ropa|viste|lleva|luce|"
    r"moreno|morena|rubio|rubia|pelirroj[ao]|"
    r"edad|años|joven|mayor|viejo|"
    r"photo|picture|image|hair|eyes|appearance|wear|wearing|looks?|"
    r"qu[eé] pinta|qu[eé] aspecto|c[oó]mo es f[ií]sicamente|c[oó]mo viste|"
    r"qu[eé] edad"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)

logger = logging.getLogger(__name__)


def _is_no_answer(text: str) -> bool:
    """True solo si la respuesta es básicamente 'no sé', sin razonamiento añadido.

    Si el LLM ha dado una inferencia, aportado contexto o usado conectores de
    razonamiento, consideramos que ya ha respondido algo útil y no disparamos
    búsqueda dirigida.
    """
    if not text:
        return True
    lower = text.lower()
    # Si contiene marcadores de razonamiento, el LLM ha aportado algo: no es no-answer.
    if any(m in lower for m in _REASONING_MARKERS):
        return False
    # Respuestas largas suelen contener contexto incluso si llevan "no aparece".
    if len(text) > 250:
        return False
    return any(s in lower for s in _NO_ANSWER_SIGNALS)


def _needs_vision(question: str) -> bool:
    return bool(_VISUAL_RE.search(question))


WELCOME = (
    "<b>Bot OSINT — Información pública</b>\n\n"
    "Hago una búsqueda web para un nombre o usuario y devuelvo los primeros enlaces "
    "ordenados por relevancia, además de buscar en LinkedIn/Instagram/X.\n"
    "Respondo preguntas distinguiendo entre <b>hecho</b>, <b>inferencia razonable</b> "
    "y <b>sin evidencia</b>. En preguntas sobre aspecto físico o fotos, analizo las "
    "imágenes públicas de las páginas consultadas con el modelo de visión de Gemini.\n\n"
    "<b>Comandos</b>\n"
    "/search &lt;nombre o usuario&gt; — Buscar\n"
    "/ask &lt;pregunta&gt; — Preguntar sobre la última búsqueda\n"
    "/clear — Borrar los datos de la sesión actual\n"
    "/help — Ayuda\n\n"
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


async def _enrich_with_vision(chat_id: int, session: dict, status) -> None:
    """Extrae imágenes de las páginas en sesión y las describe con Gemini."""
    pages = session.get("pages") or {}
    if not pages:
        return

    loop = asyncio.get_event_loop()

    if session.get("image_urls") is None:
        try:
            await status.edit_text("Buscando imágenes en las páginas…")
        except Exception:  # noqa: BLE001
            pass

        tasks = [
            loop.run_in_executor(None, fetch_page_images, url, 2)
            for url in list(pages.keys())[:5]
        ]
        page_results = await asyncio.gather(*tasks, return_exceptions=True)

        all_imgs: list[dict] = []
        seen_urls: set[str] = set()
        for r in page_results:
            if isinstance(r, Exception):
                continue
            for img in r or []:
                u = img.get("url")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    all_imgs.append(img)
        session["image_urls"] = all_imgs[:5]  # tope: 5 imágenes por sesión
        set_session(chat_id, session)

    image_urls = session.get("image_urls") or []
    if not image_urls:
        return

    described = session.get("image_descriptions") or {}
    todo = [img for img in image_urls if img.get("url") not in described]
    if not todo:
        return

    try:
        await status.edit_text(f"Analizando {len(todo)} imagen(es)…")
    except Exception:  # noqa: BLE001
        pass

    new_descs = await describe_images(todo)
    described.update(new_descs)
    session["image_descriptions"] = described
    set_session(chat_id, session)


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

        if session.get("pages") is None:
            session["pages"] = await fetch_top_pages(session)
            set_session(update.effective_chat.id, session)

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

        if _needs_vision(question):
            await _enrich_with_vision(update.effective_chat.id, session, status)

        answer = answer_question(session, question)

        note = ""
        if _is_no_answer(answer):
            person = session.get("query", "")
            if person:
                await status.edit_text("Buscando más fuentes…")
                new_pages = await targeted_search(
                    person, question, session.get("pages") or {}
                )
                if new_pages:
                    session.setdefault("pages", {}).update(new_pages)
                    if _needs_vision(question):
                        session["image_urls"] = None
                    set_session(update.effective_chat.id, session)
                    if _needs_vision(question):
                        await _enrich_with_vision(
                            update.effective_chat.id, session, status
                        )
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
