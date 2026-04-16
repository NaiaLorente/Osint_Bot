"""Obtención de datos públicos de un usuario de GitHub."""
import logging

import requests

from config import GITHUB_TOKEN

logger = logging.getLogger(__name__)

API = "https://api.github.com"


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "OSINT-Bot"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def search_github(username: str) -> dict | None:
    """Si `username` parece un handle de GitHub, devuelve su perfil público."""
    # Evita llamar a la API con frases con espacios.
    if not username or " " in username or "/" in username:
        return None

    try:
        r = requests.get(f"{API}/users/{username}", headers=_headers(), timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()

        # Top repos por estrellas.
        repos_r = requests.get(
            f"{API}/users/{username}/repos",
            params={"sort": "stars", "per_page": 5, "type": "owner"},
            headers=_headers(),
            timeout=10,
        )
        top_repos = []
        if repos_r.status_code == 200:
            repos = sorted(
                repos_r.json(),
                key=lambda x: x.get("stargazers_count", 0),
                reverse=True,
            )
            top_repos = [
                {
                    "name": repo["name"],
                    "stars": repo["stargazers_count"],
                    "description": repo.get("description"),
                    "url": repo["html_url"],
                    "language": repo.get("language"),
                }
                for repo in repos[:5]
            ]

        return {
            "login": data.get("login"),
            "name": data.get("name"),
            "bio": data.get("bio"),
            "company": data.get("company"),
            "location": data.get("location"),
            "email": data.get("email"),
            "blog": data.get("blog"),
            "twitter_username": data.get("twitter_username"),
            "public_repos": data.get("public_repos"),
            "followers": data.get("followers"),
            "following": data.get("following"),
            "created_at": data.get("created_at"),
            "url": data.get("html_url"),
            "avatar_url": data.get("avatar_url"),
            "top_repos": top_repos,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Error en GitHub: %s", exc)
        return None
