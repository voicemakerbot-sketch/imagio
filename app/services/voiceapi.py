"""VoiceAPI v2 client with async task polling and multi-key pool."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

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
    """Raised when a generation task ends with status=failed."""


# Progress callback type alias
ProgressCallback = Optional[Callable[..., Coroutine[Any, Any, None]]]


# ---------------------------------------------------------------------------
# Single-key async client (v2)
# ---------------------------------------------------------------------------


class VoiceAPIClient:
    """Async client for VoiceAPI **v2** (task-based generation).

    Workflow:
        POST /v2/image/generate  → task_id
        GET  /v2/image/tasks/{id}/status  → poll until completed/failed
        GET  /v2/image/tasks/{id}/result  → image data
    """

    TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
    POLL_INTERVAL = 2.0  # seconds between status checks
    POLL_TIMEOUT = 180.0  # max wait for a single task

    def __init__(
        self,
        base_url: str,
        api_key: str,
        proxy_url: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        client_args: Dict[str, Any] = {
            "base_url": base_url.rstrip("/"),
            "timeout": httpx.Timeout(timeout),
            "headers": {"X-API-Key": api_key},
        }
        if proxy_url:
            client_args["proxy"] = proxy_url
        self._client = httpx.AsyncClient(**client_args)
        self._api_key = api_key

    # -- v2 create task -------------------------------------------------------

    async def submit_generate(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "1:1",
        generation_mode: str = "quality",
        num_images: int = 1,
        prompt_upsampling: bool = True,
    ) -> Dict[str, Any]:
        """POST /v2/image/generate – submit a generation task."""
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "generation_mode": generation_mode,
            "num_images": num_images,
            "prompt_upsampling": prompt_upsampling,
        }
        resp = await self._client.post("/v2/image/generate", json=payload)
        if resp.status_code == 429:
            raise VoiceAPIRateLimitError("Rate limit exceeded (429)")
        resp.raise_for_status()
        return resp.json()

    # -- v2 edit task ---------------------------------------------------------

    async def submit_edit(
        self,
        prompt: str,
        image_bytes: bytes,
        *,
        aspect_ratio: str = "1:1",
        generation_mode: str = "quality",
        num_images: int = 1,
        prompt_upsampling: bool = True,
    ) -> Dict[str, Any]:
        """POST /v2/image/edit – submit an edit task (multipart)."""
        files = {"image": ("source.png", image_bytes, "image/png")}
        data: Dict[str, Any] = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "generation_mode": generation_mode,
            "num_images": str(num_images),
            "prompt_upsampling": str(prompt_upsampling).lower(),
        }
        resp = await self._client.post("/v2/image/edit", data=data, files=files)
        if resp.status_code == 429:
            raise VoiceAPIRateLimitError("Rate limit exceeded (429)")
        resp.raise_for_status()
        return resp.json()

    # -- poll status ----------------------------------------------------------

    async def poll_task(
        self,
        task_id: int,
        *,
        on_progress: ProgressCallback = None,
    ) -> Dict[str, Any]:
        """Poll GET /v2/image/tasks/{id}/status until terminal status."""
        start = time.monotonic()
        prev_status: str = ""
        prev_progress: float = -1
        while True:
            elapsed = time.monotonic() - start
            if elapsed > self.POLL_TIMEOUT:
                raise VoiceAPIError(f"Task {task_id} timed out after {self.POLL_TIMEOUT}s")

            resp = await self._client.get(f"/v2/image/tasks/{task_id}/status")
            resp.raise_for_status()
            status_data = resp.json()

            current_status = status_data.get("status", "unknown")
            progress = status_data.get("progress", 0)

            # Log only when status or progress actually changes
            if current_status != prev_status or progress != prev_progress:
                logger.debug(
                    "Task %s: status=%s progress=%.1f elapsed=%.0fs",
                    task_id, current_status, progress, elapsed,
                )
                prev_status = current_status
                prev_progress = progress

            if on_progress:
                await on_progress(current_status, progress, status_data)

            if current_status in self.TERMINAL_STATUSES:
                if current_status == "failed":
                    error_msg = status_data.get("error_message", "Unknown error")
                    raise VoiceAPITaskFailed(f"Task {task_id} failed: {error_msg}")
                if current_status == "cancelled":
                    raise VoiceAPIError(f"Task {task_id} was cancelled")
                return status_data

            await asyncio.sleep(self.POLL_INTERVAL)

    # -- fetch result ---------------------------------------------------------

    async def get_result(
        self,
        task_id: int,
        *,
        image_base64: bool = True,
        fmt: str = "png",
    ) -> Dict[str, Any]:
        """GET /v2/image/tasks/{id}/result – fetch completed result."""
        params: Dict[str, Any] = {
            "image_base64": str(image_base64).lower(),
            "format": fmt,
        }
        resp = await self._client.get(f"/v2/image/tasks/{task_id}/result", params=params)
        resp.raise_for_status()
        result = resp.json()
        # Log keys only – image data is too large
        logger.debug("Result for task %s – keys: %s", task_id, list(result.keys()))
        return result

    # -- lifecycle ------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "VoiceAPIClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()


# ---------------------------------------------------------------------------
# Multi-key pool with round-robin & 429 fallback
# ---------------------------------------------------------------------------


# Concurrency limits
MAX_CONCURRENT_PER_KEY = 3
MAX_CONCURRENT_PER_USER = 2


class VoiceAPIPool:
    """Manages multiple VoiceAPIClient instances with round-robin key rotation.

    On 429 the pool marks the key as temporarily exhausted and tries the next.
    Semaphores enforce per-key (3) and per-user (2) concurrency limits.
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
        self._key_semaphores: Dict[str, asyncio.Semaphore] = {
            key: asyncio.Semaphore(MAX_CONCURRENT_PER_KEY) for key in self._keys
        }
        self._user_semaphores: Dict[int, asyncio.Semaphore] = {}

    def _get_user_semaphore(self, user_id: int) -> asyncio.Semaphore:
        if user_id not in self._user_semaphores:
            self._user_semaphores[user_id] = asyncio.Semaphore(MAX_CONCURRENT_PER_USER)
        return self._user_semaphores[user_id]

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

    async def submit_generate(
        self, *, user_id: int = 0, **kwargs: Any,
    ) -> tuple[VoiceAPIClient, Dict[str, Any]]:
        """Try to submit across all keys with concurrency control."""
        user_sem = self._get_user_semaphore(user_id)
        async with user_sem:
            last_exc: Optional[Exception] = None
            for _ in range(len(self._keys)):
                key = self._next_key()
                key_sem = self._key_semaphores[key]
                async with key_sem:
                    client = self._get_client(key)
                    try:
                        result = await client.submit_generate(**kwargs)
                        logger.debug("submit_generate succeeded with key …%s", key[-8:])
                        return client, result
                    except VoiceAPIRateLimitError as exc:
                        logger.warning("Key …%s hit 429, rotating", key[-8:])
                        last_exc = exc
                        continue
            raise last_exc or VoiceAPIRateLimitError("All API keys exhausted (429)")

    async def submit_edit(
        self, *, user_id: int = 0, **kwargs: Any,
    ) -> tuple[VoiceAPIClient, Dict[str, Any]]:
        """Try to submit edit across all keys with concurrency control."""
        user_sem = self._get_user_semaphore(user_id)
        async with user_sem:
            last_exc: Optional[Exception] = None
            for _ in range(len(self._keys)):
                key = self._next_key()
                key_sem = self._key_semaphores[key]
                async with key_sem:
                    client = self._get_client(key)
                    try:
                        result = await client.submit_edit(**kwargs)
                        logger.debug("submit_edit succeeded with key …%s", key[-8:])
                        return client, result
                    except VoiceAPIRateLimitError as exc:
                        logger.warning("Key …%s hit 429, rotating", key[-8:])
                        last_exc = exc
                        continue
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


async def generate_image_v2(
    *,
    prompt: str,
    aspect_ratio: str = "1:1",
    generation_mode: str = "quality",
    num_images: int = 1,
    on_progress: ProgressCallback = None,
    user_id: int = 0,
) -> Dict[str, Any]:
    """Full flow: submit → poll → result.  Returns the /result JSON."""
    pool = get_pool()
    client, submit_resp = await pool.submit_generate(
        user_id=user_id,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        generation_mode=generation_mode,
        num_images=num_images,
    )
    task_id = submit_resp["task_id"]
    logger.info("Task %s submitted (mode=%s, images=%d)", task_id, generation_mode, num_images)

    await client.poll_task(task_id, on_progress=on_progress)

    result = await client.get_result(task_id, image_base64=True, fmt="png")
    logger.info("Task %s completed", task_id)
    return result


async def edit_image_v2(
    *,
    prompt: str,
    image_bytes: bytes,
    aspect_ratio: str = "1:1",
    generation_mode: str = "quality",
    num_images: int = 1,
    on_progress: ProgressCallback = None,
    user_id: int = 0,
) -> Dict[str, Any]:
    """Full edit flow: submit → poll → result."""
    pool = get_pool()
    client, submit_resp = await pool.submit_edit(
        user_id=user_id,
        prompt=prompt,
        image_bytes=image_bytes,
        aspect_ratio=aspect_ratio,
        generation_mode=generation_mode,
        num_images=num_images,
    )
    task_id = submit_resp["task_id"]
    logger.info("Edit task %s submitted", task_id)

    await client.poll_task(task_id, on_progress=on_progress)

    result = await client.get_result(task_id, image_base64=True, fmt="png")
    logger.info("Edit task %s completed", task_id)
    return result
