"""Singleton factory for WayForPayClient."""

from __future__ import annotations

from typing import Optional

from app.services.wayforpay import WayForPayClient

_client: Optional[WayForPayClient] = None


def get_wayforpay_client() -> Optional[WayForPayClient]:
    """Return a configured WayForPayClient, or None if payments are not enabled."""
    global _client
    from app.core.config import get_settings

    s = get_settings()
    if not s.payments_enabled:
        return None
    if _client is None:
        _client = WayForPayClient(
            login=s.wayforpay_merchant_login,
            secret=s.wayforpay_merchant_secret,
            domain=s.wayforpay_merchant_domain,
            password=s.wayforpay_merchant_password,
        )
    return _client
