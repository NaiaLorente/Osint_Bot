"""Integración con la API pública de GitHub.

Usa la REST API v3, que es pública y gratuita. Sin token: 60 req/h.
Con GITHUB_TOKEN (en .env) sube a 5000 req/h. Solo lee datos PÚBLICOS:
perfil declarado por el usuario, repos públicos, lenguajes, fechas de actividad.

Nada de aquí cruza login walls — son datos que el usuario expone explícitamente.

Archivo destinado a: sources/github.py
"""
import logging
import os
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "OSINT-Bot/1.0",
}
if GITHUB_TOKEN:
    _HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# Captura usuarios y repos de URLs tipo github.com/usuario o github.com/usuario/repo
_GH_URL_RE = re.compile(
    r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38})?)(?:/([A-Za-z0-9._-]+))?",
    re.IGNORECASE,
)

# Subrutas que NO son usuarios
_NOT_A_USER = {
    "orgs", "topics", "search", "marketplace", "explore", "events",
    "trending", "collections", "settings", "notifications", "pulls",
    "issues", "about", "pricing", "features", "security", "enterprise",
    "login", "join", "logout", "sponsors", "readme", "contact",
}


def extract_github_users(urls: list[str]) -> list[str]:
    """Extrae nombres de usuario únicos a partir de URLs."""
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        m = _GH_URL_RE.search(url or "")
        if not m:
            continue
        user = m.group(1)
        if not user or user.lower() in _NOT_A_USER:
            continue
        if user not in seen:
            seen.add(user)
            out.append(user)
    return out


def fetch_user(username: str, timeout: int = 10) -> Optional[dict]:
    """Perfil público de un usuario. Devuelve None si no existe / hay error."""
    try:
        resp = requests.get(
            f"https://api.github.com/users/{username}",
            headers=_HEADERS, timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error en GitHub user %s: %s", username, exc)
        return None
    if resp.status_code != 200:
        return None
    d = resp.json()
    return {
        "login": d.get("login"),
        "name": d.get("name"),
        "bio": d.get("bio"),
        "company": d.get("company"),
        "location": d.get("location"),
        "blog": d.get("blog"),
        "email": d.get("email"),                       # raro pero a veces sí
        "twitter_username": d.get("twitter_username"),
        "public_repos": d.get("public_repos"),
        "public_gists": d.get("public_gists"),
        "followers": d.get("followers"),
        "following": d.get("following"),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
        "html_url": d.get("html_url"),
        "hireable": d.get("hireable"),
    }


def fetch_user_repos(username: str, max_repos: int = 10, timeout: int = 10) -> list[dict]:
    """Repos públicos ordenados por última actualización (señal de actividad)."""
    try:
        resp = requests.get(
            f"https://api.github.com/users/{username}/repos",
            headers=_HEADERS,
            params={"sort": "updated", "per_page": max_repos, "type": "owner"},
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error en repos de %s: %s", username, exc)
        return []
    if resp.status_code != 200:
        return []
    out = []
    for r in resp.json():
        out.append({
            "name": r.get("name"),
            "description": r.get("description"),
            "language": r.get("language"),
            "stars": r.get("stargazers_count"),
            "forks": r.get("forks_count"),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "pushed_at": r.get("pushed_at"),
            "html_url": r.get("html_url"),
            "topics": r.get("topics") or [],
            "is_fork": r.get("fork"),
            "archived": r.get("archived"),
        })
    return out


def gather_github_info(urls: list[str], max_users: int = 3) -> dict:
    """Pipeline: de una lista de URLs saca usuarios y trae perfil + repos."""
    users = extract_github_users(urls)
    info: dict = {}
    for user in users[:max_users]:
        profile = fetch_user(user)
        if not profile:
            continue
        info[user] = {
            "profile": profile,
            "repos": fetch_user_repos(user, max_repos=10),
        }
    return info
