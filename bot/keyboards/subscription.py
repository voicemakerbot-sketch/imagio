"""Subscription-related inline keyboards."""

from __future__ import annotations

from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import SubscriptionPlan
from bot.localization.messages import get_message


def build_plans_keyboard(
    plans: List[SubscriptionPlan],
    current_tier: str,
    language: str,
) -> InlineKeyboardMarkup:
    """Build a keyboard with available subscription plans."""
    buttons: list[list[InlineKeyboardButton]] = []

    tier_emoji = {"premium": "⭐", "pro": "🚀"}
    for plan in plans:
        if plan.tier == current_tier:
            continue  # Don't show the plan user already has
        emoji = tier_emoji.get(plan.tier, "💎")
        label = f"{emoji} {plan.name} — ${plan.price:.0f}/{get_message('subscription.per_month', language)}"
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"pay:{plan.id}")
        ])

    buttons.append([
        InlineKeyboardButton(
            text=get_message("subscription.back", language),
            callback_data="genmenu:back",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_payment_keyboard(
    payment_url: str,
    order_ref: str,
    language: str,
) -> InlineKeyboardMarkup:
    """Build keyboard with payment link + check button."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"💳 {get_message('subscription.pay_btn', language)}",
            url=payment_url,
        )],
        [InlineKeyboardButton(
            text=f"✅ {get_message('subscription.check_btn', language)}",
            callback_data=f"check_payment:{order_ref}",
        )],
        [InlineKeyboardButton(
            text=get_message("subscription.back", language),
            callback_data="menu:subscription",
        )],
    ])


def build_active_subscription_keyboard(language: str) -> InlineKeyboardMarkup:
    """Build keyboard for users with active subscriptions."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"❌ {get_message('subscription.cancel_btn', language)}",
            callback_data="cancel_sub",
        )],
        [InlineKeyboardButton(
            text=get_message("subscription.back", language),
            callback_data="genmenu:back",
        )],
    ])


def build_cancel_confirm_keyboard(language: str) -> InlineKeyboardMarkup:
    """Build confirmation keyboard for cancellation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"✅ {get_message('subscription.cancel_yes', language)}",
                callback_data="cancel_sub:yes",
            ),
            InlineKeyboardButton(
                text=f"❌ {get_message('subscription.cancel_no', language)}",
                callback_data="menu:subscription",
            ),
        ],
    ])
