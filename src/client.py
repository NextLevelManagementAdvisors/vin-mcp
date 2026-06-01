"""NHTSA vPIC API client.

Async httpx client with a TTL cache. vPIC data is public-domain US government
data and static per VIN, so the cache is purely to avoid hammering NHTSA's
automated rate-control mechanism — there is no TOS retention ceiling to clamp.
"""

import asyncio
import json
from typing import Any, Dict, Optional

import httpx
import structlog
from cachetools import TTLCache

from src import config

logger = structlog.get_logger(__name__)


class VpicAPIError(Exception):
    """Raised for vPIC API / transport errors."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"vPIC API Error ({status_code}): {detail}")


def _make_cache_key(method: str, url: str, payload: Any) -> str:
    return f"{method}|{url}|{json.dumps(payload, sort_keys=True, default=str)}"


class VpicClient:
    """Async HTTP client for the NHTSA vPIC API with response caching."""

    def __init__(
        self,
        base_url: str = config.VPIC_BASE_URL,
        cache_ttl: int = config.VPIC_CACHE_TTL_SECONDS,
        cache_maxsize: int = config.VPIC_CACHE_MAXSIZE,
        timeout: float = config.VPIC_TIMEOUT_SECONDS,
    ):
        self.base_url = base_url.rstrip("/")
        self._cache: TTLCache = TTLCache(maxsize=cache_maxsize, ttl=cache_ttl)
        self._cache_lock = asyncio.Lock()
        self.client = httpx.AsyncClient(
            headers={"Accept": "application/json"},
            timeout=timeout,
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    async def get(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        merged = {k: v for k, v in (params or {}).items() if v is not None}
        merged["format"] = "json"
        url = self._url(path)
        key = _make_cache_key("GET", url, merged)

        async with self._cache_lock:
            if key in self._cache:
                return self._cache[key]

        log = logger.bind(method="GET", url=url, params=merged)
        try:
            resp = await self.client.get(url, params=merged)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            log.error("vPIC HTTP error", status=e.response.status_code)
            raise VpicAPIError(e.response.status_code, e.response.text[:500])
        except Exception as e:  # network, JSON, etc.
            log.error("vPIC request failed", error=str(e))
            raise VpicAPIError(0, str(e))

        async with self._cache_lock:
            self._cache[key] = data
        return data

    async def post_form(
        self, path: str, form: Dict[str, Any]
    ) -> Dict[str, Any]:
        payload = {**form, "format": "json"}
        url = self._url(path)
        key = _make_cache_key("POST", url, payload)

        async with self._cache_lock:
            if key in self._cache:
                return self._cache[key]

        log = logger.bind(method="POST", url=url)
        try:
            resp = await self.client.post(url, data=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            log.error("vPIC HTTP error", status=e.response.status_code)
            raise VpicAPIError(e.response.status_code, e.response.text[:500])
        except Exception as e:
            log.error("vPIC request failed", error=str(e))
            raise VpicAPIError(0, str(e))

        async with self._cache_lock:
            self._cache[key] = data
        return data


# Module-level singleton used by the tool modules.
client = VpicClient()
