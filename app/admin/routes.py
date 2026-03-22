"""Admin panel API routes — login/logout, stats, users CRUD."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.admin.auth import (
    ADMIN_COOKIE_MAX_AGE,
    ADMIN_COOKIE_NAME,
    ADMIN_COOKIE_VALUE,
    ADMIN_PANEL_PASSWORD,
    _compare_secret,
    is_admin_authenticated,
    require_admin,
)
from app.admin.templates import ADMIN_HTML, render_login_page
from app.db.models import Payment, Preset, Subscription, SubscriptionPlan, User
from app.db.session import AsyncSessionFactory

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Admin Panel"])


# ════════════════════════════════════════════════════════════════
# HTML PAGES
# ════════════════════════════════════════════════════════════════

@router.get("/admin")
async def admin_panel(request: Request):
    if not is_admin_authenticated(request):
        return HTMLResponse(content=render_login_page())
    return HTMLResponse(content=ADMIN_HTML)


@router.get("/admin/login")
async def admin_login_page(request: Request):
    if is_admin_authenticated(request):
        return RedirectResponse(url="/admin", status_code=303)
    return HTMLResponse(content=render_login_page())


@router.post("/admin/login")
async def admin_login(password: str = Form(...)):
    if not _compare_secret(password, ADMIN_PANEL_PASSWORD):
        return HTMLResponse(content=render_login_page("Невірний пароль"), status_code=401)

    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        ADMIN_COOKIE_VALUE,
        max_age=ADMIN_COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=False,  # set True behind HTTPS
    )
    return response


@router.post("/admin/logout")
async def admin_logout():
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(ADMIN_COOKIE_NAME)
    return response


# ════════════════════════════════════════════════════════════════
# API — STATS
# ════════════════════════════════════════════════════════════════

@router.get("/admin/api/stats")
async def get_stats(auth=Depends(require_admin)):
    try:
        async with AsyncSessionFactory() as session:
            total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0

            # Active in last 7 days
            week_ago = datetime.utcnow() - timedelta(days=7)
            active_7d = (
                await session.execute(
                    select(func.count(User.id)).where(User.updated_at >= week_ago)
                )
            ).scalar() or 0

            premium_users = (
                await session.execute(
                    select(func.count(User.id)).where(
                        User.subscription_tier.in_(["premium", "pro"])
                    )
                )
            ).scalar() or 0

            frozen_users = (
                await session.execute(
                    select(func.count(User.id)).where(User.subscription_tier == "frozen")
                )
            ).scalar() or 0

            # Subscriptions
            successful_payments = (
                await session.execute(
                    select(func.count(Subscription.id)).where(Subscription.status == "active")
                )
            ).scalar() or 0

            # Revenue from approved payments
            total_revenue = (
                await session.execute(
                    select(func.coalesce(func.sum(Payment.amount), 0)).where(
                        Payment.status == "approved"
                    )
                )
            ).scalar() or 0

            # Total payments count (all statuses)
            total_payments_count = (
                await session.execute(select(func.count(Payment.id)))
            ).scalar() or 0

            # Total generations — we don't have a generations table yet, count presets as proxy
            total_presets = (await session.execute(select(func.count(Preset.id)))).scalar() or 0

            return JSONResponse({
                "total_users": total_users,
                "active_7d": active_7d,
                "premium_users": premium_users,
                "frozen_users": frozen_users,
                "successful_payments": successful_payments,
                "total_revenue": float(total_revenue),
                "total_payments_count": total_payments_count,
                "total_generations": total_presets,  # placeholder
            })
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════
# API — USERS (list)
# ════════════════════════════════════════════════════════════════

@router.get("/admin/api/users")
async def get_users(
    search: Optional[str] = None,
    status: Optional[str] = None,
    auth=Depends(require_admin),
):
    try:
        async with AsyncSessionFactory() as session:
            stmt = (
                select(User)
                .options(selectinload(User.subscriptions), selectinload(User.presets))
                .order_by(User.created_at.desc())
                .limit(500)
            )

            # Search filter
            if search:
                like = f"%{search}%"
                stmt = stmt.where(
                    User.username.ilike(like)
                    | User.telegram_id.cast(str).contains(search)
                )

            result = await session.execute(stmt)
            users: List[User] = list(result.scalars().all())

            data = []
            for u in users:
                # Find active subscription expiry
                active_sub = next((s for s in u.subscriptions if s.status == "active"), None)
                sub_expires = None
                if active_sub and active_sub.expires_at:
                    sub_expires = active_sub.expires_at.isoformat()

                row = {
                    "id": u.id,
                    "telegram_id": u.telegram_id,
                    "username": u.username,
                    "subscription_tier": u.subscription_tier or "free",
                    "sub_expires": sub_expires,
                    "presets_count": len(u.presets),
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "updated_at": u.updated_at.isoformat() if u.updated_at else None,
                }
                data.append(row)

            # Status filter by tier
            if status:
                data = [d for d in data if d["subscription_tier"] == status]

            return JSONResponse(data)
    except Exception as e:
        logger.error(f"Users list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════
# API — USERS (single)
# ════════════════════════════════════════════════════════════════

@router.get("/admin/api/users/{user_id}")
async def get_user(user_id: int, auth=Depends(require_admin)):
    try:
        async with AsyncSessionFactory() as session:
            stmt = (
                select(User)
                .options(selectinload(User.subscriptions), selectinload(User.presets))
                .where(User.id == user_id)
            )
            result = await session.execute(stmt)
            u = result.scalar_one_or_none()
            if not u:
                raise HTTPException(status_code=404, detail="Not found")

            active_sub = next((s for s in u.subscriptions if s.status == "active"), None)
            sub_expires = None
            if active_sub and active_sub.expires_at:
                sub_expires = active_sub.expires_at.isoformat()

            return JSONResponse({
                "id": u.id,
                "telegram_id": u.telegram_id,
                "username": u.username,
                "language": u.language,
                "subscription_tier": u.subscription_tier or "free",
                "sub_expires": sub_expires,
                "presets_count": len(u.presets),
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "updated_at": u.updated_at.isoformat() if u.updated_at else None,
                "presets": [
                    {
                        "name": p.name,
                        "aspect_ratio": p.aspect_ratio,
                        "num_variants": p.num_variants,
                        "style_suffix": p.style_suffix,
                        "is_active": p.is_active,
                    }
                    for p in u.presets
                ],
                "subscriptions": [
                    {
                        "id": s.id,
                        "provider": s.provider,
                        "status": s.status,
                        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                        "created_at": s.created_at.isoformat() if s.created_at else None,
                    }
                    for s in u.subscriptions
                ],
            })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User detail error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════
# API — USERS (update)
# ════════════════════════════════════════════════════════════════

@router.put("/admin/api/users/{user_id}")
async def update_user(user_id: int, data: Dict, auth=Depends(require_admin)):
    try:
        async with AsyncSessionFactory() as session:
            stmt = select(User).options(selectinload(User.presets)).where(User.id == user_id)
            result = await session.execute(stmt)
            u = result.scalar_one_or_none()
            if not u:
                raise HTTPException(status_code=404, detail="Not found")

            if "language" in data:
                u.language = data["language"]
            if "subscription_tier" in data and data["subscription_tier"] in ("free", "premium", "pro", "frozen"):
                new_tier = data["subscription_tier"]
                old_tier = u.subscription_tier
                u.subscription_tier = new_tier

                # Auto-deactivate presets when downgrading from pro
                if old_tier == "pro" and new_tier != "pro":
                    for preset in u.presets:
                        preset.is_active = False
                    logger.info(
                        "Deactivated presets for user %s (tier %s → %s)",
                        u.telegram_id, old_tier, new_tier,
                    )

            u.updated_at = datetime.utcnow()
            await session.commit()

            logger.info(f"Admin updated user {u.telegram_id}: {list(data.keys())}")
            return JSONResponse({"status": "ok"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════
# API — PAYMENTS (list)
# ════════════════════════════════════════════════════════════════

@router.get("/admin/api/payments")
async def get_payments(
    status: Optional[str] = None,
    search: Optional[str] = None,
    auth=Depends(require_admin),
):
    try:
        async with AsyncSessionFactory() as session:
            stmt = (
                select(Payment)
                .order_by(Payment.created_at.desc())
                .limit(500)
            )
            if status:
                stmt = stmt.where(Payment.status == status)
            if search:
                like = f"%{search}%"
                stmt = stmt.where(
                    Payment.order_reference.ilike(like)
                    | Payment.card_pan.ilike(like)
                )

            result = await session.execute(stmt)
            payments = list(result.scalars().all())

            # Resolve usernames
            user_ids = {p.user_id for p in payments}
            users_map: Dict[int, User] = {}
            if user_ids:
                users_result = await session.execute(
                    select(User).where(User.id.in_(user_ids))
                )
                users_map = {u.id: u for u in users_result.scalars().all()}

            data = []
            for p in payments:
                u = users_map.get(p.user_id)
                data.append({
                    "id": p.id,
                    "order_reference": p.order_reference,
                    "user_id": p.user_id,
                    "telegram_id": u.telegram_id if u else None,
                    "username": u.username if u else None,
                    "amount": p.amount,
                    "currency": p.currency,
                    "plan_id": p.plan_id,
                    "status": p.status,
                    "provider": p.provider,
                    "card_pan": p.card_pan,
                    "card_type": p.card_type,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                })

            return JSONResponse(data)
    except Exception as e:
        logger.error(f"Payments list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════
# API — SUBSCRIPTION PLANS (list + update)
# ════════════════════════════════════════════════════════════════

@router.get("/admin/api/plans")
async def get_plans(auth=Depends(require_admin)):
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(SubscriptionPlan).order_by(SubscriptionPlan.sort_order)
            )
            plans = list(result.scalars().all())
            return JSONResponse([
                {
                    "id": p.id,
                    "name": p.name,
                    "price": p.price,
                    "currency": p.currency,
                    "period_days": p.period_days,
                    "tier": p.tier,
                    "description": p.description,
                    "is_active": p.is_active,
                    "sort_order": p.sort_order,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in plans
            ])
    except Exception as e:
        logger.error(f"Plans list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/admin/api/plans/{plan_id}")
async def update_plan(plan_id: str, data: Dict, auth=Depends(require_admin)):
    try:
        async with AsyncSessionFactory() as session:
            plan = await session.get(SubscriptionPlan, plan_id)
            if not plan:
                raise HTTPException(status_code=404, detail="Plan not found")

            if "price" in data:
                plan.price = float(data["price"])
            if "is_active" in data:
                plan.is_active = bool(data["is_active"])
            if "name" in data:
                plan.name = data["name"]
            if "description" in data:
                plan.description = data["description"]

            await session.commit()
            logger.info(f"Admin updated plan {plan_id}: {list(data.keys())}")
            return JSONResponse({"status": "ok"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Plan update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
