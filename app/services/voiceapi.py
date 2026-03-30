"""VoiceAPI v1 client — synchronous image generation with multi-key pool.

v1 is a blocking API: one POST request, wait for result.
Endpoints:
    POST /v1/image/create  → {image_b64} or PNG file
    POST /v1/image/edit    → {image_b64} or PNG file
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VoiceAPIError(RuntimeError):
    """Generic VoiceAPI error."""


class VoiceAPIRateLimitError(VoiceAPIError):
    """Raised when API returns 429 – too many requests."""


class VoiceAPITaskFailed(VoiceAPIError):
    """Raised when generation fails (content violation, timeout, etc.)."""


# Map HTTP status codes to error descriptions
_HTTP_ERROR_MAP: Dict[int, str] = {
    400: "Bad request",
    401: "Unauthorized",
    403: "Forbidden or content violation",
    422: "Validation error",
    429: "Rate limit exceeded",
    500: "Internal server error",
    502: "External service error",
    503: "Service temporarily unavailable",
    504: "Generation timeout",
}


# ---------------------------------------------------------------------------
# Single-key async client (v1 — synchronous / blocking API)
# ---------------------------------------------------------------------------


class VoiceAPIClient:
    """Async HTTP client for VoiceAPI **v1** (synchronous generation).

    v1 blocks until the image is ready — no task polling needed.
    Timeout must be generous (up to 180s for complex prompts).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        proxy_url: Optional[str] = None,
        timeout: float = 180.0,
    ) -> None:
        client_args: Dict[str, Any] = {
            "base_url": base_url.rstrip("/"),
            "timeout": httpx.Timeout(timeout, connect=30.0),
            "headers": {"X-API-Key": api_key},
        }
        if proxy_url:
            client_args["proxy"] = proxy_url
        self._client = httpx.AsyncClient(**client_args)
        self._api_key = api_key

    # -- v1 create ------------------------------------------------------------

    async def create_image(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "1:1",
        generation_mode: str = "quality",
        prompt_upsampling: bool = True,
    ) -> Dict[str, Any]:
        """POST /v1/image/create — blocks until image is ready.

        Returns JSON with ``image_b64`` key.
        """
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "generation_mode": generation_mode,
            "prompt_upsampling": prompt_upsampling,
        }
        url = "/v1/image/create"
        logger.info("POST %s payload_keys=%s", url, list(payload.keys()))
        resp = await self._client.post(url, json=payload)
        logger.info(
            "POST %s → status=%d content_length=%s",
            url, resp.status_code, resp.headers.get("content-length", "?"),
        )
        self._raise_for_status(resp)
        return resp.json()

    # -- v1 edit --------------------------------------------------------------

    async def edit_image(
        self,
        reference_image_b64: str,
        edit_instruction: str,
        *,
        aspect_ratio: str = "1:1",
        generation_mode: str = "quality",
        prompt_upsampling: bool = True,
    ) -> Dict[str, Any]:
        """POST /v1/image/edit — blocks until edited image is ready.

        Accepts base64-encoded reference image and text instruction.
        Returns JSON with ``image_b64`` key.
        """
        payload: Dict[str, Any] = {
            "reference_image_b64": reference_image_b64,
            "edit_instruction": edit_instruction,
            "aspect_ratio": aspect_ratio,
            "generation_mode": generation_mode,
            "prompt_upsampling": prompt_upsampling,
        }
        url = "/v1/image/edit"
        logger.info("POST %s payload_keys=%s", url, list(payload.keys()))
        resp = await self._client.post(url, json=payload)
        logger.info(
            "POST %s → status=%d content_length=%s",
            url, resp.status_code, resp.headers.get("content-length", "?"),
        )
        self._raise_for_status(resp)
        return resp.json()

    # -- error handling -------------------------------------------------------

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        """Raise typed exceptions based on HTTP status code."""
        if resp.is_success:
            return

        status = resp.status_code

        # Try to extract error details from JSON body
        detail = ""
        error_code = ""
        try:
            body = resp.json()
            detail = body.get("detail", "")
            error_code = body.get("error_code", "")
        except Exception:
            detail = resp.text[:200] if resp.text else ""

        desc = _HTTP_ERROR_MAP.get(status, f"HTTP {status}")
        msg = f"{desc}: {detail}" if detail else desc
        if error_code:
            msg = f"[{error_code}] {msg}"

        logger.error("API error: status=%d error_code=%s detail=%s", status, error_code, detail)

        if status == 429:
            raise VoiceAPIRateLimitError(msg)
        if status in (403, 422, 500, 502, 503, 504):
            raise VoiceAPITaskFailed(msg)

        # Generic fallback
        raise VoiceAPIError(msg)

    # -- lifecycle ------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "VoiceAPIClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()


# ---------------------------------------------------------------------------
# Multi-key pool with round-robin, 429 fallback & global concurrency
# ---------------------------------------------------------------------------

# Per-key concurrency: how many simultaneous requests one API key handles
MAX_CONCURRENT_PER_KEY = 3
# Per-user concurrency bounds (dynamic fair-share)
MIN_CONCURRENT_PER_USER = 2   # guaranteed minimum even under heavy load
MAX_CONCURRENT_PER_USER = 8   # ceiling even when bot is idle
# Global concurrency: total simultaneous requests across all keys / users.
# This protects the external API from overload when 50+ users are active.
# With 10 keys × 3 per key = 30 max, we cap at 20 for safety margin.
MAX_GLOBAL_CONCURRENT = 20


class _FairShareLimiter:
    """Dynamic per-user concurrency that adapts to current load.

    When only 1 user is active → they get up to MAX_CONCURRENT_PER_USER slots.
    When many users are active → each gets at least MIN_CONCURRENT_PER_USER.
    Fair-share formula: clamp(GLOBAL / active_users, MIN, MAX).
    """

    def __init__(self) -> None:
        self._active: Dict[int, int] = {}  # user_id → current in-flight count
        self._lock = asyncio.Lock()

    @property
    def active_user_count(self) -> int:
        return len(self._active)

    def _user_limit(self) -> int:
        """Calculate per-user slot limit based on current active users."""
        n = max(1, len(self._active))
        fair = MAX_GLOBAL_CONCURRENT // n
        return max(MIN_CONCURRENT_PER_USER, min(MAX_CONCURRENT_PER_USER, fair))

    async def acquire(self, user_id: int) -> None:
        """Wait until user can start a new request (fair-share)."""
        while True:
            async with self._lock:
                current = self._active.get(user_id, 0)
                limit = self._user_limit()
                if current < limit:
                    self._active[user_id] = current + 1
                    return
            # Slot not available — yield and retry
            await asyncio.sleep(0.1)

    async def release(self, user_id: int) -> None:
        """Release a slot after request completes."""
        async with self._lock:
            current = self._active.get(user_id, 0)
            if current <= 1:
                self._active.pop(user_id, None)
            else:
                self._active[user_id] = current - 1


class VoiceAPIPool:
    """Manages multiple VoiceAPIClient instances with round-robin key rotation.

    Concurrency is controlled at three levels:
    1. **Global semaphore** — caps total parallel requests to the external API
    2. **Per-key semaphore** — prevents a single key from being overloaded
    3. **Fair-share limiter** — dynamic per-user limits that adapt to load:
       - 1 user active → up to 8 parallel slots (fast story generation)
       - 5 users active → ~4 slots each
       - 10+ users → 2 slots each (guaranteed minimum)

    On 429 the pool marks the key as temporarily exhausted and tries the next.
    """

    def __init__(
        self,
        base_url: str,
        api_keys: List[str],
        proxy_url: Optional[str] = None,
    ) -> None:
        if not api_keys:
            raise ValueError("At least one API key is required")
        self._base_url = base_url
        self._proxy_url = proxy_url
        self._keys = list(api_keys)
        self._index = 0
        self._clients: Dict[str, VoiceAPIClient] = {}

        # Semaphores
        self._global_semaphore = asyncio.Semaphore(MAX_GLOBAL_CONCURRENT)
        self._key_semaphores: Dict[str, asyncio.Semaphore] = {
            key: asyncio.Semaphore(MAX_CONCURRENT_PER_KEY) for key in self._keys
        }
        self._fair_share = _FairShareLimiter()

        logger.info(
            "VoiceAPIPool initialized: base_url=%s keys=%d global_limit=%d per_key=%d "
            "per_user=%d-%d (dynamic fair-share)",
            base_url, len(self._keys), MAX_GLOBAL_CONCURRENT, MAX_CONCURRENT_PER_KEY,
            MIN_CONCURRENT_PER_USER, MAX_CONCURRENT_PER_USER,
        )

    def _get_client(self, key: str) -> VoiceAPIClient:
        if key not in self._clients:
            self._clients[key] = VoiceAPIClient(
                base_url=self._base_url,
                api_key=key,
                proxy_url=self._proxy_url,
            )
        return self._clients[key]

    def _next_key(self) -> str:
        key = self._keys[self._index % len(self._keys)]
        self._index += 1
        return key

    async def create_image(
        self, *, user_id: int = 0, **kwargs: Any,
    ) -> Dict[str, Any]:
        """Try /v1/image/create with fair-share + global + per-key concurrency."""
        await self._fair_share.acquire(user_id)
        try:
            async with self._global_semaphore:
                return await self._try_across_keys("create_image", **kwargs)
        finally:
            await self._fair_share.release(user_id)

    async def edit_image(
        self, *, user_id: int = 0, **kwargs: Any,
    ) -> Dict[str, Any]:
        """Try /v1/image/edit with fair-share + global + per-key concurrency."""
        await self._fair_share.acquire(user_id)
        try:
            async with self._global_semaphore:
                return await self._try_across_keys("edit_image", **kwargs)
        finally:
            await self._fair_share.release(user_id)

    async def _try_across_keys(self, method_name: str, **kwargs: Any) -> Dict[str, Any]:
        """Rotate through API keys, skip 429'd ones."""
        last_exc: Optional[Exception] = None
        for _ in range(len(self._keys)):
            key = self._next_key()
            key_sem = self._key_semaphores[key]
            async with key_sem:
                client = self._get_client(key)
                try:
                    method = getattr(client, method_name)
                    result = await method(**kwargs)
                    logger.debug("%s succeeded with key …%s", method_name, key[-8:])
                    return result
                except VoiceAPIRateLimitError as exc:
                    logger.warning("Key …%s hit 429, rotating", key[-8:])
                    last_exc = exc
                    continue
                except Exception as exc:
                    logger.error(
                        "%s failed with key …%s: %s: %s",
                        method_name, key[-8:], type(exc).__name__, exc,
                    )
                    raise
        raise last_exc or VoiceAPIRateLimitError("All API keys exhausted (429)")

    async def close(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()


# ---------------------------------------------------------------------------
# Module-level pool singleton
# ---------------------------------------------------------------------------

_pool: Optional[VoiceAPIPool] = None


def get_pool() -> VoiceAPIPool:
    """Return (and lazily create) the shared key pool."""
    global _pool  # noqa: PLW0603
    if _pool is None:
        _pool = VoiceAPIPool(
            base_url=str(settings.voice_api_base_url),
            api_keys=settings.voice_api_keys,
            proxy_url=settings.resolved_proxy_url,
        )
    return _pool


# ---------------------------------------------------------------------------
# High-level helpers used by bot handlers
# ---------------------------------------------------------------------------


async def generate_image(
    *,
    prompt: str,
    aspect_ratio: str = "1:1",
    generation_mode: str = "quality",
    num_images: int = 1,
    user_id: int = 0,
) -> List[str]:
    """Generate image(s) via v1 synchronous API.

    For ``num_images > 1``, fires N parallel requests through the pool.
    Returns a list of base64-encoded image strings.
    """
    pool = get_pool()

    async def _single_create() -> str:
        result = await pool.create_image(
            user_id=user_id,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            generation_mode=generation_mode,
        )
        b64 = result.get("image_b64", "")
        if not b64:
            raise VoiceAPIError("Empty image result from API")
        return b64

    start = time.monotonic()
    logger.info(
        "generate_image: prompt=%r ratio=%s mode=%s num=%d user=%d",
        prompt[:80], aspect_ratio, generation_mode, num_images, user_id,
    )

    if num_images == 1:
        images = [await _single_create()]
    else:
        # Fire parallel requests for multiple variants
        tasks = [asyncio.create_task(_single_create()) for _ in range(num_images)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        images: List[str] = []
        errors: List[Exception] = []
        for r in results:
            if isinstance(r, Exception):
                errors.append(r)
            else:
                images.append(r)

        if not images:
            # All failed — re-raise the first error
            raise errors[0] if errors else VoiceAPIError("No images generated")

        if errors:
            logger.warning(
                "generate_image: %d/%d variants failed: %s",
                len(errors), num_images, errors[0],
            )

    elapsed = time.monotonic() - start
    logger.info("generate_image: %d images in %.1fs", len(images), elapsed)
    return images


async def edit_image(
    *,
    edit_instruction: str,
    reference_image_b64: str,
    aspect_ratio: str = "1:1",
    generation_mode: str = "quality",
    num_images: int = 1,
    user_id: int = 0,
) -> List[str]:
    """Edit image(s) via v1 synchronous API.

    For ``num_images > 1``, fires N parallel requests through the pool.
    Returns a list of base64-encoded image strings.
    """
    pool = get_pool()

    async def _single_edit() -> str:
        result = await pool.edit_image(
            user_id=user_id,
            reference_image_b64=reference_image_b64,
            edit_instruction=edit_instruction,
            aspect_ratio=aspect_ratio,
            generation_mode=generation_mode,
        )
        b64 = result.get("image_b64", "")
        if not b64:
            raise VoiceAPIError("Empty image result from edit API")
        return b64

    start = time.monotonic()
    logger.info(
        "edit_image: instruction=%r ratio=%s num=%d user=%d",
        edit_instruction[:80], aspect_ratio, num_images, user_id,
    )

    if num_images == 1:
        images = [await _single_edit()]
    else:
        tasks = [asyncio.create_task(_single_edit()) for _ in range(num_images)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        images: List[str] = []
        errors: List[Exception] = []
        for r in results:
            if isinstance(r, Exception):
                errors.append(r)
            else:
                images.append(r)

        if not images:
            raise errors[0] if errors else VoiceAPIError("No images edited")

        if errors:
            logger.warning(
                "edit_image: %d/%d variants failed: %s",
                len(errors), num_images, errors[0],
            )

    elapsed = time.monotonic() - start
    logger.info("edit_image: %d images in %.1fs", len(images), elapsed)
    return images
