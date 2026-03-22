"""Subscription handlers — plan selection, payment, cancellation."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Payment, Subscription, SubscriptionPlan, User
from app.db.session import AsyncSessionFactory
from app.services.feature_access import TIER_LABELS
from app.services.payment_client import get_wayforpay_client
from app.services.subscription_manager import SubscriptionManager
from bot.keyboards.subscription import (
    build_active_subscription_keyboard,
    build_cancel_confirm_keyboard,
    build_payment_keyboard,
    build_plans_keyboard,
)
from bot.localization.messages import get_message

logger = logging.getLogger(__name__)
router = Router(name="subscription")


def _get_lang(callback: CallbackQuery) -> str:
    from bot.localization.messages import normalize_language
    user = callback.from_user
    return normalize_language(user.language_code if user else None)


# ─── Subscription cabinet ─────────────────────────────────

@router.callback_query(F.data == "menu:subscription")
async def show_subscription(callback: CallbackQuery) -> None:
    """Show subscription cabinet: current tier, plans, or cancel option."""
    lang = _get_lang(callback)
    settings = get_settings()

    if not settings.payments_enabled:
        await callback.message.edit_text(get_message("subscription.not_available", lang))
        await callback.answer()
        return

    async with AsyncSessionFactory() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        if not user:
            await callback.message.edit_text(get_message("subscription.not_available", lang))
            await callback.answer()
            return

        tier = user.subscription_tier or "free"
        tier_label = TIER_LABELS.get(tier, tier)

        # Check for active paid subscription
        active_sub = await session.scalar(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.status == "active",
                Subscription.activation_type == "payment",
            )
        )

        if tier in ("premium", "pro") and active_sub:
            # Active paid subscription — show status + cancel button
            expires_str = active_sub.expires_at.strftime("%d.%m.%Y") if active_sub.expires_at else "—"
            text = (
                f"💎 <b>{get_message('subscription.cabinet', lang)}</b>\n\n"
                f"📌 {get_message('subscription.current_plan', lang)}: <b>{tier_label}</b>\n"
                f"📅 {get_message('subscription.expires', lang)}: <b>{expires_str}</b>\n"
                f"🔄 {get_message('subscription.auto_renew', lang)}: "
                f"{'✅' if active_sub.is_recurring else '❌'}"
            )
            await callback.message.edit_text(
                text, reply_markup=build_active_subscription_keyboard(lang),
            )
        elif tier == "frozen":
            # Frozen — show message + plans with descriptions
            plans = await _get_active_plans(session)
            plans_text = _build_plans_description(plans, lang)
            text = (
                f"❄️ <b>{get_message('subscription.frozen_msg', lang)}</b>\n\n"
                f"{plans_text}\n\n"
                f"{get_message('subscription.choose_plan', lang)}"
            )
            await callback.message.edit_text(
                text, reply_markup=build_plans_keyboard(plans, tier, lang),
            )
        else:
            # Free tier — show plans with descriptions
            plans = await _get_active_plans(session)
            plans_text = _build_plans_description(plans, lang)
            text = (
                f"💎 <b>{get_message('subscription.cabinet', lang)}</b>\n\n"
                f"📌 {get_message('subscription.current_plan', lang)}: <b>{tier_label}</b>\n"
                f"📊 {get_message('subscription.daily_limit_info', lang)}\n\n"
                f"{plans_text}\n\n"
                f"{get_message('subscription.choose_plan', lang)}"
            )
            await callback.message.edit_text(
                text, reply_markup=build_plans_keyboard(plans, tier, lang),
            )

    await callback.answer()


# ─── Initiate payment ─────────────────────────────────────

@router.callback_query(F.data.startswith("pay:"))
async def initiate_payment(callback: CallbackQuery) -> None:
    """User selected a plan → create payment → show payment URL."""
    lang = _get_lang(callback)
    plan_id = callback.data.split(":", 1)[1]
    settings = get_settings()
    wfp = get_wayforpay_client()

    if not wfp or not settings.payments_enabled:
        await callback.message.edit_text(get_message("subscription.not_available", lang))
        await callback.answer()
        return

    async with AsyncSessionFactory() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        if not user:
            await callback.answer(get_message("subscription.not_available", lang), show_alert=True)
            return

        mgr = SubscriptionManager(session, wfp, callback.bot)
        try:
            url, payment = await mgr.initiate_payment(
                user=user,
                plan_id=plan_id,
                service_url=settings.payment_service_url,
                form_base_url=settings.payment_form_url,
                return_url=f"{settings.webhook_base_url}/api/payments/pay/return",
            )
        except ValueError as e:
            await callback.answer(str(e), show_alert=True)
            return

        plan = await session.get(SubscriptionPlan, plan_id)
        plan_name = plan.name if plan else plan_id

        await callback.message.edit_text(
            f"💳 <b>{plan_name}</b> — ${payment.amount:.0f}/{get_message('subscription.per_month', lang)}\n\n"
            f"{get_message('subscription.payment_instructions', lang)}",
            reply_markup=build_payment_keyboard(url, payment.order_reference, lang),
        )

    await callback.answer()


# ─── Check payment status ─────────────────────────────────

@router.callback_query(F.data.startswith("check_payment:"))
async def check_payment_status(callback: CallbackQuery) -> None:
    """User pressed 'I paid' → check status via WayForPay API."""
    lang = _get_lang(callback)
    order_ref = callback.data.split(":", 1)[1]
    wfp = get_wayforpay_client()

    if not wfp:
        await callback.answer(get_message("subscription.not_available", lang), show_alert=True)
        return

    result = await wfp.check_order_status(order_ref)
    tx_status = str(result.get("transactionStatus", "")).upper()

    if tx_status in ("APPROVED", "COMPLETE"):
        # Activate via the manager
        async with AsyncSessionFactory() as session:
            mgr = SubscriptionManager(session, wfp, callback.bot)
            await mgr.handle_approved(result)

        await callback.message.edit_text(
            f"✅ {get_message('subscription.check_success', lang)}",
        )
    elif tx_status in ("PENDING", "INPROCESSING", "CREATED"):
        await callback.answer(get_message("subscription.check_pending", lang), show_alert=True)
    else:
        await callback.answer(get_message("subscription.check_failed", lang), show_alert=True)

    await callback.answer()


# ─── Cancel subscription ──────────────────────────────────

@router.callback_query(F.data == "cancel_sub")
async def cancel_sub_confirm(callback: CallbackQuery) -> None:
    """Show cancellation confirmation."""
    lang = _get_lang(callback)
    await callback.message.edit_text(
        f"⚠️ {get_message('subscription.cancel_confirm', lang)}",
        reply_markup=build_cancel_confirm_keyboard(lang),
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_sub:yes")
async def cancel_sub_execute(callback: CallbackQuery) -> None:
    """Actually cancel the subscription."""
    lang = _get_lang(callback)
    wfp = get_wayforpay_client()

    if not wfp:
        await callback.answer(get_message("subscription.not_available", lang), show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        if not user:
            await callback.answer(get_message("subscription.not_available", lang), show_alert=True)
            return

        mgr = SubscriptionManager(session, wfp, callback.bot)
        cancelled = await mgr.cancel_by_user(user)

    if cancelled:
        await callback.message.edit_text(
            f"✅ {get_message('subscription.cancelled', lang)}",
        )
    else:
        await callback.answer(get_message("subscription.no_active_sub", lang), show_alert=True)

    await callback.answer()


# ─── Helpers ──────────────────────────────────────────────

def _build_plans_description(plans: list[SubscriptionPlan], lang: str) -> str:
    """Build formatted text block with plan names, prices, and feature descriptions."""
    tier_emoji = {"premium": "⭐", "pro": "🚀"}
    desc_keys = {
        "premium": "subscription.plan_premium_desc",
        "pro": "subscription.plan_pro_desc",
    }
    parts = []
    for plan in plans:
        emoji = tier_emoji.get(plan.tier, "💎")
        desc = get_message(desc_keys.get(plan.tier, ""), lang) if plan.tier in desc_keys else (plan.description or "")
        parts.append(
            f"{emoji} <b>{plan.name}</b> — ${plan.price:.0f}/{get_message('subscription.per_month', lang)}\n{desc}"
        )
    return "\n\n".join(parts)


async def _get_active_plans(session) -> list[SubscriptionPlan]:
    result = await session.execute(
        select(SubscriptionPlan)
        .where(SubscriptionPlan.is_active == True)  # noqa: E712
        .order_by(SubscriptionPlan.sort_order)
    )
    return list(result.scalars().all())
