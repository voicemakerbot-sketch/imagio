"""Subscription lifecycle manager.

Orchestrates payment initiation, webhook handling (approved/declined),
user-initiated cancellation, and expiration checks.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment, Subscription, SubscriptionPlan, User
from app.services.wayforpay import WayForPayClient

logger = logging.getLogger(__name__)


class SubscriptionManager:
    """Manages the full subscription lifecycle."""

    def __init__(self, session: AsyncSession, wfp: WayForPayClient, bot: Bot) -> None:
        self._session = session
        self._wfp = wfp
        self._bot = bot

    # ─── Payment initiation ───────────────────────────────────

    async def initiate_payment(
        self,
        user: User,
        plan_id: str,
        service_url: str,
        form_base_url: str,
        return_url: str,
    ) -> Tuple[str, Payment]:
        """Create a pending payment and return (payment_url, payment).

        Raises ValueError if plan not found or user already has active paid sub.
        """
        # Load plan
        plan = await self._session.get(SubscriptionPlan, plan_id)
        if not plan or not plan.is_active:
            raise ValueError(f"Plan '{plan_id}' not found or inactive")

        # Check for existing active paid subscription
        active_sub = await self._session.scalar(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.status == "active",
                Subscription.activation_type == "payment",
            )
        )
        if active_sub and active_sub.expires_at and active_sub.expires_at > datetime.now(timezone.utc):
            raise ValueError("User already has an active paid subscription")

        # Check for existing pending payment on same plan → reuse
        existing = await self._session.scalar(
            select(Payment).where(
                Payment.user_id == user.id,
                Payment.plan_id == plan_id,
                Payment.status == "pending",
            )
        )
        if existing:
            params = self._wfp.build_payment_params(
                order_ref=existing.order_reference,
                amount=existing.amount,
                currency=existing.currency,
                product_name=f"Imagio {plan.name}",
                service_url=service_url,
                return_url=return_url,
            )
            url = self._wfp.build_payment_url(params, form_base_url)
            return url, existing

        # Create new payment
        order_ref = f"IMG_{user.telegram_id}_{int(time.time())}"
        payment = Payment(
            user_id=user.id,
            order_reference=order_ref,
            amount=plan.price,
            currency=plan.currency,
            plan_id=plan.id,
            status="pending",
        )
        self._session.add(payment)
        await self._session.flush()

        params = self._wfp.build_payment_params(
            order_ref=order_ref,
            amount=plan.price,
            currency=plan.currency,
            product_name=f"Imagio {plan.name}",
            service_url=service_url,
            return_url=return_url,
        )
        url = self._wfp.build_payment_url(params, form_base_url)
        await self._session.commit()
        return url, payment

    # ─── Webhook: APPROVED ────────────────────────────────────

    async def handle_approved(self, payload: dict) -> None:
        """Handle an APPROVED webhook from WayForPay."""
        order_ref = payload.get("orderReference", "")
        user = await self._find_user_for_webhook(order_ref)
        if not user:
            logger.error("APPROVED webhook: user not found for %s", order_ref)
            return

        # Try to find a matching Payment (first payment)
        payment = await self._session.scalar(
            select(Payment).where(Payment.order_reference == order_ref)
        )

        if payment:
            # ── First payment ──
            plan = await self._session.get(SubscriptionPlan, payment.plan_id)
            if not plan:
                logger.error("Plan %s not found for payment %s", payment.plan_id, order_ref)
                return

            await self._activate_subscription(user, plan, order_ref)
            payment.status = "approved"
            payment.card_pan = payload.get("cardPan")
            payment.card_type = payload.get("cardType")
            payment.webhook_payload = str(payload)
            payment.updated_at = datetime.now(timezone.utc)
            await self._session.commit()

            try:
                expires_str = user.subscriptions[-1].expires_at.strftime("%d.%m.%Y") if user.subscriptions else "—"
                await self._bot.send_message(
                    user.telegram_id,
                    f"✅ Підписку <b>{plan.name}</b> активовано до {expires_str}!\n"
                    f"Дякуємо за оплату 🎉",
                )
            except Exception:
                logger.exception("Failed to send activation message to %s", user.telegram_id)
        else:
            # ── Recurring payment (no Payment record) ──
            sub = await self._session.scalar(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.status == "active",
                    Subscription.is_recurring == True,  # noqa: E712
                )
            )
            if sub:
                sub.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                sub.retry_count = 0
                user.daily_generations = 0
                await self._session.commit()

                try:
                    expires_str = sub.expires_at.strftime("%d.%m.%Y")
                    await self._bot.send_message(
                        user.telegram_id,
                        f"🔄 Підписку подовжено до {expires_str}!",
                    )
                except Exception:
                    logger.exception("Failed to send renewal message to %s", user.telegram_id)
            else:
                logger.warning("Recurring APPROVED but no active subscription for user %s", user.telegram_id)

    # ─── Webhook: DECLINED ────────────────────────────────────

    async def handle_declined(self, payload: dict) -> None:
        """Handle a DECLINED webhook from WayForPay.

        1st decline → keep access for 1 day, warn user.
        2nd decline → freeze account, remove recurring.
        """
        order_ref = payload.get("orderReference", "")
        user = await self._find_user_for_webhook(order_ref)
        if not user:
            logger.error("DECLINED webhook: user not found for %s", order_ref)
            return

        sub = await self._session.scalar(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.status == "active",
                Subscription.is_recurring == True,  # noqa: E712
            )
        )
        if not sub:
            logger.warning("DECLINED but no active recurring subscription for %s", order_ref)
            return

        sub.retry_count += 1

        if sub.retry_count == 1:
            # First decline — warn, keep access for 1 more day
            logger.info("First decline for user %s, sending warning", user.telegram_id)
            await self._session.commit()
            try:
                await self._bot.send_message(
                    user.telegram_id,
                    "⚠️ <b>Оплата не пройшла!</b>\n\n"
                    "Завтра буде ще одна спроба списання.\n"
                    "Якщо оплата знову не пройде — підписку буде скасовано.",
                )
            except Exception:
                logger.exception("Failed to send decline warning to %s", user.telegram_id)
        else:
            # 2nd+ decline — freeze
            logger.info("Second decline for user %s, freezing", user.telegram_id)
            user.subscription_tier = "frozen"
            sub.status = "cancelled"
            sub.cancelled_at = datetime.now(timezone.utc)
            await self._session.commit()

            # Try to remove regular payment at WayForPay
            if sub.regular_order_id:
                try:
                    await self._wfp.remove_regular(sub.regular_order_id)
                except Exception:
                    logger.exception("Failed to REMOVE regular for %s", sub.regular_order_id)

            try:
                await self._bot.send_message(
                    user.telegram_id,
                    "❌ <b>Підписку скасовано</b> через неуспішну оплату.\n\n"
                    "Ви можете оформити нову підписку в меню 💎 Підписка.",
                )
            except Exception:
                logger.exception("Failed to send freeze message to %s", user.telegram_id)

    # ─── User-initiated cancellation ──────────────────────────

    async def cancel_by_user(self, user: User) -> bool:
        """Cancel the user's recurring subscription.

        Returns True if cancelled, False if no active subscription found.
        """
        sub = await self._session.scalar(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.status == "active",
                Subscription.activation_type == "payment",
            )
        )
        if not sub:
            return False

        # Remove recurring at WayForPay
        if sub.regular_order_id and sub.is_recurring:
            try:
                result = await self._wfp.remove_regular(sub.regular_order_id)
                logger.info("Regular REMOVE result: %s", result.get("reasonCode"))
            except Exception:
                logger.exception("Failed to REMOVE regular for %s", sub.regular_order_id)

        sub.status = "cancelled"
        sub.is_recurring = False
        sub.cancelled_at = datetime.now(timezone.utc)
        user.subscription_tier = "free"

        # Deactivate presets if downgrading from pro
        if sub.plan_id and "pro" in sub.plan_id:
            from sqlalchemy import update as sa_update
            from app.db.models import Preset
            await self._session.execute(
                sa_update(Preset).where(Preset.user_id == user.id).values(is_active=False)
            )

        await self._session.commit()
        return True

    # ─── Expiration check (background) ────────────────────────

    async def check_expired_subscriptions(self) -> int:
        """Find expired, non-recurring subscriptions and downgrade to free.

        Recurring subscriptions are NOT touched — WayForPay handles those via webhooks.
        Returns number of expired subscriptions processed.
        """
        now = datetime.now(timezone.utc)
        stmt = select(Subscription).where(
            Subscription.status == "active",
            Subscription.is_recurring == False,  # noqa: E712
            Subscription.expires_at < now,
        )
        result = await self._session.execute(stmt)
        expired = list(result.scalars().all())

        count = 0
        for sub in expired:
            user = await self._session.get(User, sub.user_id)
            if not user:
                continue
            user.subscription_tier = "free"
            sub.status = "expired"
            count += 1
            logger.info("Expired subscription for user %s (plan %s)", user.telegram_id, sub.plan_id)

        if count:
            await self._session.commit()
        return count

    # ─── Internal helpers ─────────────────────────────────────

    async def _find_user_for_webhook(self, order_ref: str) -> Optional[User]:
        """Cascade search: parse telegram_id from order_ref → Payment → Subscription."""
        # 1. Parse telegram_id from IMG_{tid}_{ts}
        parts = order_ref.split("_")
        if len(parts) >= 2:
            try:
                tid = int(parts[1])
                user = await self._session.scalar(
                    select(User).where(User.telegram_id == tid)
                )
                if user:
                    return user
            except (ValueError, IndexError):
                pass

        # 2. Look up via Payment table
        payment = await self._session.scalar(
            select(Payment).where(Payment.order_reference == order_ref)
        )
        if payment:
            return await self._session.get(User, payment.user_id)

        # 3. Look up via Subscription regular_order_id
        sub = await self._session.scalar(
            select(Subscription).where(Subscription.regular_order_id == order_ref)
        )
        if sub:
            return await self._session.get(User, sub.user_id)

        # 4. Try stripping WFP suffix (they sometimes append _N)
        if "_" in order_ref:
            base_ref = "_".join(order_ref.rsplit("_", 1)[:-1])
            if base_ref != order_ref:
                return await self._find_user_for_webhook(base_ref)

        return None

    async def _activate_subscription(
        self,
        user: User,
        plan: SubscriptionPlan,
        order_ref: str,
    ) -> None:
        """Activate a subscription for a user based on a plan."""
        expires = datetime.now(timezone.utc) + timedelta(days=plan.period_days)

        # Deactivate any previous active subscriptions
        prev_subs = await self._session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.status == "active",
            )
        )
        for prev in prev_subs.scalars().all():
            prev.status = "replaced"

        sub = Subscription(
            user_id=user.id,
            provider="wayforpay",
            status="active",
            expires_at=expires,
            plan_id=plan.id,
            is_recurring=True,
            regular_order_id=order_ref,
            retry_count=0,
            activation_type="payment",
        )
        self._session.add(sub)

        user.subscription_tier = plan.tier
        user.daily_generations = 0
