"""Rate limiter y caché para APIs externas."""

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)


class RateLimiter:
    """Limita requests por API con cooldown adaptativo."""

    def __init__(self, min_delay: float = 0.5, max_retries: int = 3):
        self.min_delay = min_delay
        self.max_retries = max_retries
        self.last_request_time: dict[str, float] = {}
        self.lock = asyncio.Lock()

    async def wait(self, key: str) -> None:
        """Espera antes de hacer un request a esta API."""
        async with self.lock:
            last_time = self.last_request_time.get(key, 0)
            elapsed = time.time() - last_time
            delay = max(0, self.min_delay - elapsed)
            if delay > 0:
                logger.debug(f"Rate limit: esperando {delay:.2f}s para {key}")
                await asyncio.sleep(delay)
            self.last_request_time[key] = time.time()


class SearchCache:
    """Cachea resultados de búsqueda por hash."""

    def __init__(self, ttl_hours: int = 24):
        self.ttl_hours = ttl_hours

    @staticmethod
    def _make_key(query: str, source: str) -> str:
        h = hashlib.md5(f"{source}:{query}".encode()).hexdigest()
        return f"{source}_{h}"

    def get(self, query: str, source: str) -> Optional[list]:
        """Obtiene resultado en caché si existe y no está expirado."""
        key = self._make_key(query, source)
        cache_file = CACHE_DIR / f"{key}.json"

        if not cache_file.exists():
            return None

        try:
            with open(cache_file) as f:
                data = json.load(f)
            
            age_hours = (time.time() - data["timestamp"]) / 3600
            if age_hours > self.ttl_hours:
                logger.debug(f"Cache expirado: {key}")
                cache_file.unlink()
                return None

            logger.debug(f"Cache hit: {key}")
            return data.get("results")
        except Exception as e:
            logger.error(f"Error leyendo caché {key}: {e}")
            return None

    def set(self, query: str, source: str, results: list) -> None:
        """Cachea un resultado de búsqueda."""
        key = self._make_key(query, source)
        cache_file = CACHE_DIR / f"{key}.json"

        try:
            with open(cache_file, "w") as f:
                json.dump(
                    {"timestamp": time.time(), "results": results},
                    f,
                )
            logger.debug(f"Cache saved: {key}")
        except Exception as e:
            logger.error(f"Error guardando caché {key}: {e}")


class LLMResponseCache:
    """Cachea respuestas de LLM por persona + pregunta."""

    def __init__(self, ttl_hours: int = 24):
        self.ttl_hours = ttl_hours

    @staticmethod
    def _make_key(person_name: str, question: str) -> str:
        """Crea clave hash de persona + pregunta."""
        h = hashlib.md5(f"{person_name}:{question}".encode()).hexdigest()
        return f"llm_{h}"

    def get(self, person_name: str, question: str) -> Optional[str]:
        """Obtiene respuesta cacheada si existe y no está expirada."""
        key = self._make_key(person_name, question)
        cache_file = CACHE_DIR / f"{key}.json"

        if not cache_file.exists():
            return None

        try:
            with open(cache_file) as f:
                data = json.load(f)
            
            age_hours = (time.time() - data["timestamp"]) / 3600
            if age_hours > self.ttl_hours:
                logger.debug(f"LLM cache expirado: {key}")
                cache_file.unlink()
                return None

            logger.info(f"LLM cache hit: {person_name} / {question[:50]}")
            return data.get("response")
        except Exception as e:
            logger.error(f"Error leyendo LLM cache {key}: {e}")
            return None

    def set(self, person_name: str, question: str, response: str) -> None:
        """Cachea una respuesta de LLM."""
        key = self._make_key(person_name, question)
        cache_file = CACHE_DIR / f"{key}.json"

        try:
            with open(cache_file, "w") as f:
                json.dump(
                    {
                        "timestamp": time.time(),
                        "response": response,
                        "person": person_name,
                        "question": question,
                    },
                    f,
                )
            logger.debug(f"LLM cache saved: {key}")
        except Exception as e:
            logger.error(f"Error guardando LLM cache {key}: {e}")


# Global instances
RATE_LIMITER = RateLimiter(min_delay=1.0)  # 1 segundo entre requests
SEARCH_CACHE = SearchCache(ttl_hours=24)
LLM_CACHE = LLMResponseCache(ttl_hours=24)
