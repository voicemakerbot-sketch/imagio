"""Admin panel authentication — cookie-based with constant-time comparison."""

import hashlib
import os
import secrets
from typing import Optional

from fastapi import HTTPException, Request

from app.core.config import settings

ADMIN_PANEL_PASSWORD: str = os.getenv("ADMIN_PANEL_PASSWORD", "Imagio_Admin_2026")
ADMIN_COOKIE_NAME: str = "imagio_admin_session"
ADMIN_COOKIE_MAX_AGE: int = 30 * 24 * 60 * 60  # 30 days
ADMIN_COOKIE_VALUE: str = hashlib.sha256(ADMIN_PANEL_PASSWORD.encode("utf-8")).hexdigest()


def _compare_secret(value: Optional[str], expected: Optional[str]) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    if value is None or expected is None:
        return False
    return secrets.compare_digest(value.encode("utf-8"), expected.encode("utf-8"))


def is_admin_authenticated(request: Request) -> bool:
    token = request.cookies.get(ADMIN_COOKIE_NAME, "")
    if not token:
        return False
    return _compare_secret(token, ADMIN_COOKIE_VALUE)


def require_admin(request: Request) -> bool:
    """FastAPI dependency that raises 401 if not authenticated."""
    if not is_admin_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True
