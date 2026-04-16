"""Almacenamiento en memoria de la sesión OSINT por chat.

Sencillo y suficiente para un bot personal. Si lo escalas a varios
usuarios, sustituye este módulo por Redis o SQLite.
"""
from threading import Lock

_sessions: dict[int, dict] = {}
_lock = Lock()


def set_session(chat_id: int, data: dict) -> None:
    with _lock:
        _sessions[chat_id] = data


def get_session(chat_id: int) -> dict | None:
    with _lock:
        return _sessions.get(chat_id)


def clear_session(chat_id: int) -> None:
    with _lock:
        _sessions.pop(chat_id, None)
