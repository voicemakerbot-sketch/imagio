# Imagio: Система оплат і підписок — План реалізації

**Goal:** Реалізувати систему оплат через WayForPay з автоматичним продовженням підписок (recurring monthly), обробкою webhook'ів та UI в Telegram-боті.

**Architecture:** Адаптація перевіреної архітектури з Voisio на async SQLAlchemy + FastAPI + Aiogram 3. Новий модуль `app/services/wayforpay.py` (API клієнт) + `app/services/subscription_manager.py` (бізнес-логіка). Нові моделі: `Payment`, `SubscriptionPlan`. Розширення існуючої `Subscription`.

**Tech Stack:** Python 3.11+, FastAPI, Aiogram 3, SQLAlchemy (async), aiosqlite, HTTPX, HMAC-MD5

**Reference:** `docs/plans/2026-03-22-voisio-payment-analysis.md`

---

## Поточний стан Imagio (факт)

### Тієри (User.subscription_tier)

| Tier | Ліміт | Фічі | Ціна |
|------|-------|-------|------|
| `free` | 10 генерацій/день | generate | $0 |
| `premium` | unlimited | generate, edit | $10/міс |
| `pro` | unlimited | generate, edit, queue, presets | $15/міс |
| `frozen` | 0 | нічого | блок |

### Feature gating — ПОВНІСТЮ працює

- `feature_access.py`: `VALID_TIERS`, `TIER_FEATURES`, `FREE_DAILY_LIMIT=10`
- `check_and_increment_generation()` — атомарна перевірка + інкремент
- `reset_daily_generations()` — скид о 00:00 UTC
- premium/pro → unlimited, free → 10/день, frozen → 0

### Моделі БД (факт)

**User:** `id`, `telegram_id`, `username`, `language`, `subscription_tier` (free/premium/pro/frozen), `daily_generations`, `created_at`, `updated_at`

**Subscription:** `id`, `user_id` (FK), `provider` (wayforpay), `status` (pending/active), `expires_at`, `payload` (JSON text), `created_at`

### Config (факт)

```python
wayforpay_merchant_id: Optional[str] = None
wayforpay_secret: Optional[str] = None
webhook_base_url: Optional[AnyHttpUrl] = None
```

---

## Рішення

| Питання | Рішення |
|---------|---------|
| Ціни | Premium = $10/міс, Pro = $15/міс |
| Валюта | USD. WFP конвертує в UAH |
| Free tier | 10 генерацій/день, скид о 00:00 |
| Order reference | `IMG_{telegram_id}_{unix_timestamp}` |
| Declined | 1-й → залишити доступ + warning. 2-й → frozen |
| Промокоди | v2 (пізніше) |
| Affiliate | v2 (пізніше) |
| Мерчант WFP | Поле відкрите, заповниться пізніше. Платежі працюють тільки коли заповнено |

---

## Фаза 0: Конфігурація

### Task 0.1: Оновити config
**Files:** Modify `app/core/config.py`

**Steps:**
1. Написати тест: `settings.payments_enabled` = False коли merchant пустий
2. Запустити → RED
3. Замінити/додати поля:
```python
# --- WayForPay ---
wayforpay_merchant_login: Optional[str] = None
wayforpay_merchant_secret: Optional[str] = None
wayforpay_merchant_password: Optional[str] = None
wayforpay_merchant_domain: str = "imagio.bot"
subscription_currency: str = "USD"

@property
def payments_enabled(self) -> bool:
    return bool(self.wayforpay_merchant_login and self.wayforpay_merchant_secret)

@property
def payment_service_url(self) -> str | None:
    if self.webhook_base_url:
        return f"{self.webhook_base_url}/api/payments/wayforpay/webhook"
    return None

@property
def payment_form_url(self) -> str | None:
    if self.webhook_base_url:
        return f"{self.webhook_base_url}/api/payments/pay"
    return None
```
4. Видалити старе `wayforpay_merchant_id` (замінено на `wayforpay_merchant_login`)
5. Запустити → GREEN
6. **Commit:** `feat: update WayForPay payment config`

---

## Фаза 1: Моделі бази даних

### Task 1.1: Модель SubscriptionPlan
**Files:** Modify `app/db/models.py`

**Steps:**
1. Failing тест:
```python
async def test_subscription_plan_creation(session):
    plan = SubscriptionPlan(
        id="premium_monthly", name="Premium", price=10.0,
        currency="USD", period_days=30, tier="premium",
    )
    session.add(plan)
    await session.commit()
    assert plan.is_active is True
    assert plan.tier == "premium"
```
2. Запустити → RED
3. Реалізувати:
```python
class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    period_days: Mapped[int] = mapped_column(Integer, default=30)
    tier: Mapped[str] = mapped_column(String(16))              # "premium" | "pro"
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```
4. Запустити → GREEN
5. **Commit:** `feat: add SubscriptionPlan model`

### Task 1.2: Модель Payment
**Files:** Modify `app/db/models.py`

**Steps:**
1. Failing тест:
```python
async def test_payment_creation(session, user):
    payment = Payment(
        user_id=user.id, order_reference="IMG_123_1711100000",
        amount=10.0, currency="USD", plan_id="premium_monthly",
    )
    session.add(payment)
    await session.commit()
    assert payment.status == "pending"
    assert payment.order_reference.startswith("IMG_")
```
2. Запустити → RED
3. Реалізувати:
```python
class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    order_reference: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    plan_id: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    provider: Mapped[str] = mapped_column(String(50), default="wayforpay")
    card_pan: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    card_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    webhook_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="payments")
```
4. Додати в User: `payments: Mapped[List["Payment"]] = relationship(...)`
5. Запустити → GREEN
6. **Commit:** `feat: add Payment model`

### Task 1.3: Розширити Subscription
**Files:** Modify `app/db/models.py`

**Steps:**
1. Failing тест
2. Додати нові поля:
```python
plan_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
regular_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
retry_count: Mapped[int] = mapped_column(Integer, default=0)
activation_type: Mapped[str] = mapped_column(String(32), default="free")
cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```
3. Запустити → GREEN
4. **Commit:** `feat: extend Subscription for recurring`

### Task 1.4: Міграція + Seed
**Files:** Create `scripts/migrate_payments.py`

**Steps:**
1. Скрипт: створити таблиці, ALTER subscriptions, seed плани:
```
premium_monthly: Premium, $10, 30d, tier=premium, sort=1
pro_monthly:     Pro,     $15, 30d, tier=pro,     sort=2
```
2. Запустити, перевірити
3. **Commit:** `feat: payment migration and seeding`

---

## Фаза 2: WayForPay API клієнт

### Task 2.1: WayForPay Client
**Files:** Create `app/services/wayforpay.py`

**Steps:**
1. Failing тест: signature calculation
2. Реалізувати:
```python
class WayForPayClient:
    PAYMENT_URL = "https://secure.wayforpay.com/pay"
    API_URL = "https://api.wayforpay.com/api"
    REGULAR_API_URL = "https://api.wayforpay.com/regularApi"

    def _calculate_signature(self, sign_string: str) -> str:
        """HMAC-MD5"""

    def build_payment_params(self, order_ref, amount, currency, product_name,
                              service_url, return_url, regular_mode="monthly",
                              regular_count=12, regular_amount=None) -> dict:

    def build_payment_url(self, params: dict, form_base_url: str) -> str:

    async def check_order_status(self, order_ref: str) -> dict:
    async def check_regular_status(self, order_ref: str) -> dict:
    async def remove_regular(self, order_ref: str) -> dict:

    def verify_webhook_signature(self, payload: dict) -> bool:
    def build_webhook_response(self, order_ref: str, status="accept") -> dict:
```
3. Тести для кожного методу
4. Запустити → GREEN
5. **Commit:** `feat: WayForPay async API client`

### Task 2.2: Client factory
**Files:** Create `app/services/payment_client.py`

**Steps:**
1. `get_wayforpay_client() -> WayForPayClient | None` (None якщо not payments_enabled)
2. Тест
3. **Commit:** `feat: WayForPay client factory`

---

## Фаза 3: Subscription Manager

### Task 3.1: Subscription Manager
**Files:** Create `app/services/subscription_manager.py`

**Steps:**
1. Failing тести
2. Реалізувати:
```python
class SubscriptionManager:
    async def initiate_payment(self, user, plan_id) -> tuple[str, Payment]:
        """
        1. Перевірка: немає active платної підписки
        2. Перевірка: pending payment → повернути старе
        3. order_ref = IMG_{telegram_id}_{timestamp}
        4. Payment(pending)
        5. Payment URL
        """

    async def handle_approved(self, payload: dict) -> None:
        """
        Перший платіж: tier=plan.tier, Subscription(active, +30d, recurring)
        Recurring: extends +30d, retry_count=0, daily_generations=0
        Telegram повідомлення
        """

    async def handle_declined(self, payload: dict) -> None:
        """
        retry 0→1: НЕ чіпати tier, warning message
        retry 1→2: tier=frozen, REMOVE regular, Telegram повідомлення
        """

    async def cancel_by_user(self, user) -> bool:
        """Regular API REMOVE, tier=free, subscription cancelled"""

    async def check_expired(self) -> int:
        """expired + NOT recurring → free"""

    async def _find_user(self, order_ref) -> User | None:
        """IMG_{tid}_{ts} → Payment → Subscription"""
```
3. Запустити → GREEN
4. **Commit:** `feat: subscription manager`

---

## Фаза 4: Webhook + Form-server

### Task 4.1: Webhook endpoint
**Files:** Create `app/api/routes/payments.py`, Modify `app/admin/routes.py`

**Steps:**
1. Видалити зламаний webhook з `admin/routes.py`
2. Новий endpoint:
```python
@router.post("/wayforpay/webhook")
async def wayforpay_webhook(request: Request):
    # verify → handle_approved / handle_declined → accept response ЗАВЖДИ
```
3. Зареєструвати в `app/main.py`
4. Тести
5. **Commit:** `feat: WayForPay webhook endpoint`

### Task 4.2: Form-server + return
**Files:** Modify `app/api/routes/payments.py`

**Steps:**
1. `GET /api/payments/pay` → auto-submit HTML form → WFP
2. `GET /api/payments/pay/return` → "Дякуємо! Поверніться в бот."
3. Тести
4. **Commit:** `feat: payment form and return page`

---

## Фаза 5: Bot UI

### Task 5.1: Клавіатури
**Files:** Create `bot/keyboards/subscription.py`

**Steps:**
1. `plans_keyboard(plans, current_tier)` → [⭐ Premium $10] [🚀 Pro $15]
2. `payment_keyboard(url, order_ref)` → [💳 Оплатити] [✅ Я оплатив]
3. `active_subscription_keyboard()` → [❌ Скасувати]
4. **Commit:** `feat: subscription keyboards`

### Task 5.2: Subscription handler
**Files:** Create `bot/handlers/subscription.py`, Modify `bot/handlers/menu.py`, Modify `bot/bot.py`

**Steps:**
1. `menu:subscription` → кабінет (tier, expires, кнопки)
2. `pay:{plan_id}` → initiate_payment → URL
3. `check_payment:{ref}` → CHECK_STATUS
4. `cancel_sub` → confirm → execute
5. Якщо `payments_enabled=False` → "Оплата тимчасово недоступна"
6. Видалити stub з menu.py, зареєструвати router в bot.py
7. **Commit:** `feat: subscription bot handler`

### Task 5.3: Локалізація
**Files:** Modify `bot/localization/messages.py`

**Steps:**
1. Ключі uk/en/es: cabinet, choose_plan, activated, renewed, declined_warning, frozen, cancelled, cancel_confirm, not_available, check_*
2. **Commit:** `feat: payment localization`

---

## Фаза 6: Адмін-панель

### Task 6.1: API + UI
**Files:** Modify `app/admin/routes.py`, `app/admin/templates.py`

**Steps:**
1. `GET /admin/api/plans`, `PUT /admin/api/plans/{id}`
2. `GET /admin/api/payments` (фільтри), `GET /admin/api/payments/stats`
3. Замінити заглушки в UI
4. **Commit:** `feat: admin payments UI`

---

## Фаза 7: Expiration checker

### Task 7.1
**Files:** Create `app/services/subscription_checker.py`, Modify `scripts/start_all.py`

**Steps:**
1. Раз на годину: expired + NOT recurring → free
2. Додати в start_all.py
3. **Commit:** `feat: subscription expiration checker`

---

## Фаза 8: Тести

### Task 8.1: E2E
- initiate → APPROVED → tier=premium
- DECLINED(1) → tier unchanged + warning
- DECLINED(2) → frozen
- cancel → free
- recurring APPROVED → extend

### Task 8.2: Webhook security
- valid/invalid signature, duplicates, unknown order

---

## Declined flow

```
WFP                    FASTAPI                    БОТ               ЮЗЕР
 │ DECLINED (1-й)       │                          │                  │
 ├─────────────────────►│ retry: 0→1               │                  │
 │                       │ tier: НЕ ЗМІНЮЄТЬСЯ      │                  │
 │                       │──── Telegram ───────────►│                  │
 │                       │                          │ ⚠️ Оплата не    │
 │                       │                          │ пройшла! Завтра  │
 │                       │                          │ ще спроба. Якщо  │
 │                       │                          │ не пройде —      │
 │                       │                          │ скасуємо.        │
 │                       │                          │                  │
 │ DECLINED (2-й)        │                          │                  │
 ├─────────────────────►│ retry: 1→2               │                  │
 │                       │ tier → frozen            │                  │
 │                       │ REMOVE regular           │                  │
 │                       │──── Telegram ───────────►│                  │
 │                       │                          │ ❌ Підписку      │
 │                       │                          │ скасовано.       │
```

## Файли

| Файл | Дія | Фаза |
|------|-----|------|
| `app/core/config.py` | Modify | 0 |
| `app/db/models.py` | Modify | 1 |
| `scripts/migrate_payments.py` | Create | 1 |
| `app/services/wayforpay.py` | Create | 2 |
| `app/services/payment_client.py` | Create | 2 |
| `app/services/subscription_manager.py` | Create | 3 |
| `app/api/routes/payments.py` | Create | 4 |
| `app/admin/routes.py` | Modify | 4, 6 |
| `app/main.py` | Modify | 4 |
| `bot/keyboards/subscription.py` | Create | 5 |
| `bot/handlers/subscription.py` | Create | 5 |
| `bot/handlers/menu.py` | Modify | 5 |
| `bot/bot.py` | Modify | 5 |
| `bot/localization/messages.py` | Modify | 5 |
| `app/admin/templates.py` | Modify | 6 |
| `app/services/subscription_checker.py` | Create | 7 |
| `scripts/start_all.py` | Modify | 7 |
| `tests/test_payment_flow.py` | Create | 8 |
| `tests/test_webhook.py` | Create | 8 |

## Час

| Фаза | ~Час |
|------|------|
| 0. Config | 20 хв |
| 1. Моделі | 1.5 год |
| 2. WFP клієнт | 2 год |
| 3. Sub Manager | 2.5 год |
| 4. Webhook + Form | 1.5 год |
| 5. Bot UI | 2.5 год |
| 6. Адмінка | 1.5 год |
| 7. Expiration | 45 хв |
| 8. Тести | 2 год |
| **Всього** | **~14 год** |
