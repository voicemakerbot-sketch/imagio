"""WayForPay payment endpoints: webhook, form-server, return page."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.config import settings
from app.db.session import AsyncSessionFactory
from app.services.payment_client import get_wayforpay_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


# ════════════════════════════════════════════════════════════════
# Webhook — receives payment notifications from WayForPay
# ════════════════════════════════════════════════════════════════

@router.post("/wayforpay/webhook")
async def wayforpay_webhook(request: Request) -> JSONResponse:
    """Process WayForPay webhook.

    ALWAYS returns an ``accept`` response — otherwise WFP retries for 4 days.
    """
    wfp = get_wayforpay_client()
    order_ref = "unknown"

    try:
        body = await request.body()
        payload: Dict[str, Any] = json.loads(body)
        order_ref = payload.get("orderReference", "unknown")
        logger.info("Webhook received: order=%s", order_ref)

        if not wfp:
            logger.warning("Payments not configured, ignoring webhook for %s", order_ref)
            return JSONResponse({"status": "accept"})

        # Verify signature (warn but don't reject — WFP will keep retrying)
        sig_valid = wfp.verify_webhook_signature(payload)
        if not sig_valid:
            logger.warning("Invalid webhook signature for %s", order_ref)

        # Determine status from various WFP payload formats
        tx_status = (
            payload.get("transactionStatus")
            or payload.get("orderStatus")
            or payload.get("status")
            or ""
        ).upper()

        logger.info("Webhook status for %s: %s (sig_valid=%s)", order_ref, tx_status, sig_valid)

        if tx_status in ("APPROVED", "COMPLETE"):
            await _handle_approved(payload)
        elif tx_status in ("DECLINED", "EXPIRED"):
            await _handle_declined(payload)
        elif tx_status in ("REFUNDED", "VOIDED"):
            logger.info("Refund/void for %s — logged only", order_ref)
        else:
            logger.info("Unhandled webhook status '%s' for %s", tx_status, order_ref)

    except Exception:
        logger.exception("Webhook processing error for %s", order_ref)

    # Always respond with accept
    if wfp:
        return JSONResponse(wfp.build_webhook_response(order_ref))
    return JSONResponse({"orderReference": order_ref, "status": "accept", "time": 0, "signature": ""})


async def _handle_approved(payload: dict) -> None:
    """Delegate to SubscriptionManager.handle_approved."""
    from bot.bot import build_bot
    from app.services.subscription_manager import SubscriptionManager

    wfp = get_wayforpay_client()
    if not wfp:
        return

    bot, _ = build_bot()
    try:
        async with AsyncSessionFactory() as session:
            mgr = SubscriptionManager(session, wfp, bot)
            await mgr.handle_approved(payload)
    finally:
        await bot.session.close()


async def _handle_declined(payload: dict) -> None:
    """Delegate to SubscriptionManager.handle_declined."""
    from bot.bot import build_bot
    from app.services.subscription_manager import SubscriptionManager

    wfp = get_wayforpay_client()
    if not wfp:
        return

    bot, _ = build_bot()
    try:
        async with AsyncSessionFactory() as session:
            mgr = SubscriptionManager(session, wfp, bot)
            await mgr.handle_declined(payload)
    finally:
        await bot.session.close()


# ════════════════════════════════════════════════════════════════
# Form-server — auto-submit HTML form redirecting to WayForPay
# ════════════════════════════════════════════════════════════════

PAYMENT_FORM_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Imagio — Оплата</title></head>
<body>
<p>Переспрямування на сторінку оплати…</p>
<form id="payForm" method="POST" action="https://secure.wayforpay.com/pay">
{fields}
</form>
<script>document.getElementById('payForm').submit();</script>
</body>
</html>"""


@router.get("/pay")
async def payment_form(request: Request) -> HTMLResponse:
    """Build an auto-submitting HTML form that POSTs to WayForPay."""
    params = dict(request.query_params)
    fields = "\n".join(
        f'<input type="hidden" name="{k}" value="{v}">'
        for k, v in params.items()
    )
    html = PAYMENT_FORM_HTML.format(fields=fields)
    return HTMLResponse(html)


# ════════════════════════════════════════════════════════════════
# Return page — user comes back after paying
# ════════════════════════════════════════════════════════════════

RETURN_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>Imagio — Дякуємо!</title>
<style>
body{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f5f5f5}
.card{background:#fff;padding:40px;border-radius:16px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.1)}
h1{margin:0 0 12px}
p{color:#555}
</style>
</head>
<body>
<div class="card">
<h1>✅ Дякуємо за оплату!</h1>
<p>Поверніться у Telegram-бот — підписку буде активовано автоматично.</p>
</div>
</body>
</html>"""


@router.get("/pay/return")
async def payment_return() -> HTMLResponse:
    """Thank-you page after WayForPay redirects the user back."""
    return HTMLResponse(RETURN_HTML)

