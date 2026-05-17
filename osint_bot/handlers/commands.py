"""Command handlers con enriquecimiento profundo de fuentes legítimas.

Flujo de /ask:
  1. Primer /ask: descarga páginas top de /search (fetch_top_pages).
  2. SIEMPRE: deep_question_search (cacheado por firma de pregunta).
  3. Una vez por sesión: enriquecimiento con datos estructurados (JSON-LD,
     OG, microdata) y GitHub API si hay URLs github.com.
  4. Si la pregunta es visual: vision sobre imágenes.
  5. LLM con todo el contexto.
  6. Último recurso: targeted_search legacy si el LLM se rinde puramente.
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
from services.osint import (
    deep_question_search,
    fetch_top_pages,
    format_results,
    question_signature,
    run_full_search,
    targeted_search,
)
from services.vision import describe_images
from sources.fetcher import fetch_page_text
from sources.github import gather_github_info
from sources.images import fetch_page_images
from sources.structured import fetch_structured_from_url
from storage.sessions import clear_session, get_session, set_session

_URL_RE = re.compile(r"https?://\S+")

_NO_ANSWER_SIGNALS = (
    "no encuentro ese dato", "no tengo esa información", "no hay información",
    "no dispongo de", "no se menciona", "no aparece", "no consta",
)
_REASONING_MARKERS = (
    " pero ", " aunque ", " sin embargo", "no obstante",
    "por tanto", "por lo tanto", " parece ", "probablemente",
    " sugiere ", " indica ", " según ", " dado que",
    " por la foto", " en la imagen", " la imagen sugiere",
    " su huella", " su perfil", " su trayectoria",
    " however", " but ", " although ",
)
_VISUAL_RE = re.compile(
    r"\b("
    r"foto|fotos|imagen|im[aá]genes|aspecto|apariencia|f[ií]sico|f[ií]sicamente|"
    r"pelo|cabello|melena|barba|bigote|ojos|gafas|sonrisa|tatuaje|piercing|"
    r"altura|complexi[oó]n|alto|alta|bajo|baja|delgad[ao]|"
    r"vestimenta|ropa|viste|lleva|luce|moreno|morena|rubio|rubia|pelirroj[ao]|"
    r"edad|años|joven|mayor|viejo|"
    r"photo|picture|image|hair|eyes|appearance|wear|wearing|looks?|"
    r"qu[eé] pinta|qu[eé] aspecto|c[oó]mo es f[ií]sicamente|c[oó]mo viste|qu[eé] edad"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)

logger = logging.getLogger(__name__)


def _is_no_answer(text: str) -> bool:
    if not text:
        return True
    lower = text.lower()
    if any(m in lower for m in _REASONING_MARKERS):
        return False
    if len(text) > 250:
        return False
    return any(s in lower for s in _NO_ANSWER_SIGNALS)


def _needs_vision(question: str) -> bool:
    return bool(_VISUAL_RE.search(question))


WELCOME = (
    "<b>Bot OSINT — Información pública</b>\n\n"
    "Hago una búsqueda multivariante y una <b>búsqueda profunda por pregunta</b>.\n"
    "Enriquezco con: <b>datos estructurados</b> (schema.org / Open Graph), "
    "<b>API pública de GitHub</b> si hay cuentas vinculadas, y <b>visión</b> "
    "sobre fotos públicas para preguntas sobre aspecto.\n"
    "Respondo distinguiendo <b>hecho</b>, <b>inferencia razonable</b> y "
    "<b>sin evidencia</b>.\n\n"
    "<b>Comandos</b>\n"
    "/search &lt;nombre o usuario&gt; — Buscar\n"
    "/ask &lt;pregunta&gt; — Preguntar sobre la última búsqueda\n"
    "/clear — Borrar sesión\n"
    "/help — Ayuda\n\n"
    "<i>Solo información pública. Respeta la privacidad y las leyes "
    "aplicables (RGPD/LOPDGDD).</i>"
)


def _authorized(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return update.effective_user and update.effective_user.id in ALLOWED_USER_IDS


async def _deny(update: Update) -> None:
    await update.message.reply_text("No estás autorizado a usar este bot.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update); return
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update); return
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update); return
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
                chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            )
        await status.delete()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error en búsqueda")
        await status.edit_text(f"Error durante la búsqueda: {exc}")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update); return
    question = " ".join(context.args).strip()
    if not question:
        await update.message.reply_text("Uso: /ask <pregunta>")
        return
    await perform_question(update, question)


# ─── Enriquecimientos ─────────────────────────────────────────────────────────

async def _enrich_structured(chat_id: int, session: dict, status) -> bool:
    """Extrae schema.org/JSON-LD/OG de las páginas en sesión.

    Solo descarga las URLs que NO se hayan procesado antes (incremental).
    Devuelve True si se añadió algo nuevo.
    """
    pages = session.get("pages") or {}
    if not pages:
        return False

    structured: dict[str, dict] = session.setdefault("structured", {})
    todo = [u for u in pages.keys() if u not in structured]
    if not todo:
        return False

    try:
        await status.edit_text(f"Extrayendo datos estructurados ({len(todo)} pág.)…")
    except Exception:  # noqa: BLE001
        pass

    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(4)

    async def _one(url: str) -> tuple[str, dict]:
        async with sem:
            data = await loop.run_in_executor(None, fetch_structured_from_url, url)
        return url, data

    results = await asyncio.gather(*[_one(u) for u in todo[:10]], return_exceptions=True)
    added = False
    for r in results:
        if isinstance(r, Exception):
            continue
        url, data = r
        if data:  # solo guardamos las que aportan algo
            structured[url] = data
            added = True
        else:
            structured[url] = {}  # marca como ya procesada para no reintentar
    set_session(chat_id, session)
    return added


async def _enrich_github(chat_id: int, session: dict, status) -> bool:
    """Si entre los resultados aparece algún github.com/<user>, trae perfil + repos.

    Cacheada: solo corre una vez por sesión.
    """
    if session.get("github") is not None:
        return False  # ya hecho (aunque sea vacío)

    web = session.get("web") or []
    pages = session.get("pages") or {}
    urls = [r.get("url") for r in web if r.get("url")] + list(pages.keys())
    if not any("github.com" in (u or "") for u in urls):
        session["github"] = {}
        set_session(chat_id, session)
        return False

    try:
        await status.edit_text("Consultando perfiles GitHub…")
    except Exception:  # noqa: BLE001
        pass

    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, gather_github_info, urls, 3)
    session["github"] = info or {}
    set_session(chat_id, session)
    return bool(info)


async def _enrich_with_vision(chat_id: int, session: dict, status) -> None:
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
            for url in list(pages.keys())[:6]
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
        session["image_urls"] = all_imgs[:6]
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


async def _proactive_deep_search(chat_id: int, session: dict, question: str, status) -> bool:
    person = session.get("query") or ""
    if not person or len(question) < 4:
        return False
    sig = question_signature(question)
    searched: list = session.setdefault("searched_sigs", [])
    if sig in searched:
        return False
    try:
        await status.edit_text(f"Búsqueda profunda ({sig})…")
    except Exception:  # noqa: BLE001
        pass
    new_pages = await deep_question_search(
        person, question, existing_pages=session.get("pages") or {},
    )
    searched.append(sig)
    if new_pages:
        session.setdefault("pages", {}).update(new_pages)
        set_session(chat_id, session)
        return True
    set_session(chat_id, session)
    return False


# ─── Q&A ──────────────────────────────────────────────────────────────────────

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
        chat_id = update.effective_chat.id

        # 1) Páginas base (primer /ask)
        if session.get("pages") is None:
            session["pages"] = await fetch_top_pages(session)
            set_session(chat_id, session)

        # 2) URLs pegadas en la pregunta
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
            set_session(chat_id, session)

        # 3) Búsqueda profunda dirigida a la pregunta (cached por firma)
        brought_new = await _proactive_deep_search(chat_id, session, question, status)

        # 4) Si entraron páginas nuevas, invalidamos caché de imágenes y forzamos
        #    una nueva pasada de extracción estructurada (los nuevos URLs no
        #    están en `structured` todavía, así que _enrich_structured los recogerá).
        if brought_new and _needs_vision(question):
            session["image_urls"] = None
            set_session(chat_id, session)

        # 5) Enriquecimiento estructurado (incremental, barato)
        await _enrich_structured(chat_id, session, status)

        # 6) GitHub (una vez por sesión)
        await _enrich_github(chat_id, session, status)

        # 7) Visión si la pregunta es visual
        if _needs_vision(question):
            await _enrich_with_vision(chat_id, session, status)

        # 8) Respuesta del LLM con todo el contexto
        answer = answer_question(session, question)

        # 9) Último recurso si se rinde sin razonar
        note = ""
        if _is_no_answer(answer):
            person = session.get("query", "")
            if person:
                await status.edit_text("Buscando más fuentes (último intento)…")
                new_pages = await targeted_search(
                    person, question, session.get("pages") or {}
                )
                if new_pages:
                    session.setdefault("pages", {}).update(new_pages)
                    if _needs_vision(question):
                        session["image_urls"] = None
                    set_session(chat_id, session)
                    await _enrich_structured(chat_id, session, status)
                    if _needs_vision(question):
                        await _enrich_with_vision(chat_id, session, status)
                    answer = answer_question(session, question)
                    note = (
                        "Esta información requería búsqueda adicional fuera de "
                        "los enlaces previos.\n\n"
                    )

        history = session.get("history") or []
        history.append({"user": question, "assistant": answer})
        session["history"] = history
        set_session(chat_id, session)
        await status.edit_text(f"{note}{answer}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error en Q&A")
        await status.edit_text(f"Error al responder: {exc}")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update); return
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
