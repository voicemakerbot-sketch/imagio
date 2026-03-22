# Аналіз системи оплат Voisio Bot

**Мета:** Документація існуючої платіжної системи в Voisio для перенесення архітектури в Imagio.
**Дата:** 2026-03-22

---

## 1. Загальна архітектура платежів

```
┌─────────────────────────────────────────────────────────────┐
│  Telegram Bot (Aiogram 2)                                   │
│  handlers/payment_handlers.py                               │
│  - Кабінет підписки, вибір плану                            │
│  - Ініціація платежу → генерація URL                        │
│  - Кнопка "Платіж здійснено" → CHECK_STATUS                 │
│  - Скасування підписки → Regular API REMOVE                 │
│  - Історія платежів                                         │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│  payments/ (бізнес-логіка)                                  │
│  ┌────────────────────────────────────────┐                 │
│  │ wayforpay_api.py (Singleton)           │                 │
│  │ - create_payment() → URL              │                 │
│  │ - check_order_status() → CHECK_STATUS │                 │
│  │ - check_subscription() → Regular STATUS│                 │
│  │ - remove_subscription() → Regular REMOVE│                │
│  │ - verify_webhook() / generate_response │                 │
│  └────────────────────────────────────────┘                 │
│  ┌────────────────────────────────────────┐                 │
│  │ subscription_manager.py (Бізнес-логіка)│                 │
│  │ - handle_approved() (перший + recurring)│                │
│  │ - handle_declined() (frozen → cancel)  │                 │
│  │ - cancel_subscription_by_user()        │                 │
│  └────────────────────────────────────────┘                 │
│  ┌────────────────────────────────────────┐                 │
│  │ wayforpay_webhook.py (FastAPI endpoint) │                │
│  │ - POST /webhook/payment                │                 │
│  │ - Верифікація підпису (5 варіантів)    │                 │
│  │ - Делегує в subscription_manager       │                 │
│  └────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│  web/app.py (FastAPI)                                       │
│  - GET  /pay         → auto-submit HTML form → WayForPay    │
│  - GET  /pay/return  → "Дякуємо" сторінка                   │
│  - POST /webhook/payment → webhook обробка                  │
└─────────────────────────────────────────────────────────────┘
                 │
         ┌───────▼────────┐
         │   WayForPay    │
         │ (secure.way..  │
         │  forpay.com)   │
         └────────────────┘
```

---

## 2. WayForPay: API та підпис

### 2.1 Credentials

| Змінна | Призначення |
|--------|-------------|
| `WAYFORPAY_MERCHANT_LOGIN` | ID мерчанта |
| `WAYFORPAY_MERCHANT_SECRET` | Секрет для HMAC підпису |
| `WAYFORPAY_MERCHANT_PASSWORD` | Для Regular API (REMOVE, STATUS) |
| `WAYFORPAY_WEBHOOK_URL` | URL для service_url параметру |

### 2.2 Підпис (HMAC-MD5)

```python
def _calculate_signature(self, sign_string: str) -> str:
    return hmac.new(
        self.merchant_secret.encode('utf-8'),
        sign_string.encode('utf-8'),
        hashlib.md5
    ).hexdigest()
```

**Рядок підпису при створенні платежу:**
```
merchantAccount;merchantDomainName;orderReference;orderDate;amount;currency;productName[];productCount[];productPrice[]
```

**Рядок підпису для відповіді на webhook:**
```
orderReference;status;time
```

**Верифікація webhook (5 варіантів, перевіряються послідовно):**

1. **Стандартний:** `merchantAccount;orderReference;amount;currency;authCode;cardPan;transactionStatus;reasonCode`
2. **З regular полями:** стандартний + `;regularMode;regularAmount;regularCount`
3. **Спрощений:** `merchantAccount;orderReference;amount;currency;orderStatus`
4. **Статусний (date):** `merchantAccount;orderReference;processingDate;status;reasonCode`
5. **Статусний (time):** `merchantAccount;orderReference;time;status;reasonCode`

### 2.3 API Endpoints WayForPay

| URL | Метод | Призначення |
|-----|-------|-------------|
| `https://secure.wayforpay.com/pay` | POST HTML form | Платіжна сторінка |
| `https://api.wayforpay.com/api` | POST JSON | CHECK_STATUS, CHARGE |
| `https://api.wayforpay.com/regularApi` | POST JSON | Regular: STATUS, REMOVE |

---

## 3. Схема бази даних

### 3.1 users (платіжні поля)

```sql
subscription_status TEXT,         -- 'start' | 'active' | 'frozen'
subscription_expires_at TEXT,     -- ISO datetime
subscription_plan TEXT,           -- 'Trial' | 'Light' | 'Безліміт'
subscription_plan_id TEXT,        -- 'trial_500' | 'light' | 'unlimited'
subscription_activation_type TEXT, -- 'trial' | 'payment' | 'promo_code' | 'admin'
subscription_chars_limit INTEGER, -- -1=unlimited, 500=trial, 1000000=light
subscription_chars_used INTEGER,
subscription_retry_count INTEGER, -- declined counter (1=frozen, ≥2=cancel)
card_pan TEXT,                    -- '5123****4321'
card_type TEXT,                   -- 'VISA' | 'MasterCard'
issuer_bank_name TEXT,
regular_order_id TEXT,            -- sub_userId_timestamp
is_recurring INTEGER,             -- 1=активна
next_payment_date TEXT,
regular_date_end TEXT,            -- 'DD.MM.YYYY'
```

### 3.2 invoices

```sql
CREATE TABLE invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    order_id TEXT UNIQUE,
    amount REAL,
    currency TEXT,
    status TEXT,          -- 'pending' | 'approved' | 'declined' | 'cancelled_declined'
    plan_id TEXT DEFAULT 'unlimited',
    message_id INTEGER,   -- Telegram message ID
    created_at TEXT,
    updated_at TEXT
);
```

### 3.3 subscription_plans

```sql
CREATE TABLE subscription_plans (
    id TEXT PRIMARY KEY,     -- 'light' | 'unlimited'
    name TEXT,
    price_uah REAL,
    currency TEXT DEFAULT 'USD',
    days INTEGER,            -- 30
    limit_chars INTEGER,     -- 1000000 | -1
    description TEXT,
    is_active INTEGER DEFAULT 1
);
```

### 3.4 affiliate таблиці

```sql
-- Промокоди блогерів
affiliate_promo_codes (code, discount_percent, blogger_name, max_uses, is_active...)
-- Зв'язок юзер↔партнер
affiliate_referrals (user_id UNIQUE, affiliate_code, discount_applied, total_paid...)
-- Комісії
affiliate_earnings (user_id, affiliate_code, payment_amount, commission_percent=20%, order_id...)
```

---

## 4. Повний потік оплати

### 4.1 Крок 1: Ініціація (юзер → бот)

1. Юзер натискає **"💎 Підписка"** → показується кабінет
2. Юзер обирає план → callback `pay:plan_id`
3. **Перевірки:**
   - Вже є активна платна підписка? → блокує
   - Є pending invoice на ту ж суму? → повертає старе посилання
   - Є affiliate знижка? → зменшує amount першого платежу
4. **Генерація order_id:** `sub_{user_id}_{unix_timestamp}`
5. **Створення invoice** в БД (status=pending)
6. **Виклик create_payment():**
   - `regularMode = "monthly"` (автопродовження)
   - `regularAmount` = повна ціна (знижка тільки на перший)
   - `regularCount = 12`
   - `regularBehavior = "preset"`
   - `serviceUrl` = webhook URL
7. Генерація URL: `{FORM_SERVER}/pay?merchantAccount=...&merchantSignature=...`
8. Показує кнопки: **"💳 Перейти до оплати"** + **"✅ Платіж здійснено"**

### 4.2 Крок 2: Оплата (юзер → WayForPay)

1. Юзер → URL → `GET /pay` → FastAPI form-server
2. Form-server → HTML з auto-submit POST form → `https://secure.wayforpay.com/pay`
3. WayForPay → платіжна сторінка → юзер платить
4. WayForPay:
   - Редірект юзера → `GET /pay/return` ("Дякуємо!")
   - Webhook → `POST /webhook/payment`

### 4.3 Крок 3: Webhook (WayForPay → сервер)

```
POST /webhook/payment  →  handle_webhook()
  ├── 1. Логування payload
  ├── 2. Верифікація підпису (5 варіантів)
  │     ⚠️ Навіть якщо підпис не співпав → accept!
  ├── 3. Визначення статусу (transactionStatus / orderStatus / status)
  │
  ├── APPROVED → handle_approved()
  │   ├── Каскадний пошук юзера:
  │   │   1. Парсити user_id з orderReference (sub_{uid}_{ts})
  │   │   2. invoices по order_id
  │   │   3. users по regular_order_id
  │   │   4. Відрізати WFP суфікс і знову
  │   ├── ПЕРШИЙ ПЛАТІЖ (invoice знайдено):
  │   │   → activate_subscription(plan_id, order_id, expires=+30d)
  │   │   → update_recurring_info(is_recurring=True, regular_order_id)
  │   │   → save card info
  │   │   → invoice status → "approved"
  │   │   → Telegram: "✅ Підписку активовано!"
  │   │   → record_affiliate_earning()
  │   └── RECURRING (invoice НЕ знайдено):
  │       → chars_used = 0, expires = +1 місяць
  │       → status = "active", retry_count = 0
  │       → Telegram: "🔄 Підписку подовжено!"
  │       → record_affiliate_earning()
  │
  ├── DECLINED → handle_declined()
  │   ├── retry_count == 1 → FROZEN
  │   │   → Telegram: "⚠️ Проблема з оплатою"
  │   └── retry_count ≥ 2 → CANCEL
  │       → Regular API REMOVE
  │       → cancel_subscription() → trial
  │       → Telegram: "❌ Підписку скасовано"
  │
  ├── REFUNDED/VOIDED → лог
  ├── PENDING → лог
  └── ЗАВЖДИ: повернути accept response
      {"orderReference":"...","status":"accept","time":123,"signature":"hmac"}
```

### 4.4 Крок 4: Ручна перевірка ("✅ Платіж здійснено")

```
check_order_status(order_id)
  → POST api.wayforpay.com/api {transactionType: "CHECK_STATUS"}
  → Approved → activate + check Regular STATUS → update is_recurring
  → Declined → invoice → "declined", повідомлення юзеру
```

---

## 5. Підпискові тієри

| Статус | Значення | Генерація |
|--------|----------|-----------|
| `start` | Trial/Free (500 символів) | ✅ |
| `active` | Платна підписка | ✅ |
| `frozen` | Проблема з оплатою | ❌ |

| Тип активації | Хто керує | Frozen? |
|---------------|-----------|---------|
| `trial` | Бот (авто-поновлення) | Ні |
| `payment` | WayForPay (webhooks) | ✅ |
| `promo_code` | Бот (по даті) | Ні |
| `admin` | Бот (по даті) | Ні |

---

## 6. Скасування підписки

**Юзером:**
1. Перевірити Regular API STATUS
2. Якщо не "removed" → REMOVE через Regular API
3. cancel_subscription() → статус = "start" (trial)

**Автоматичне при declined:**
- 1-й declined → frozen
- 2-й declined → STATUS → REMOVE → cancel → trial

---

## 7. Промокоди

### Звичайні промокоди
- Одноразові або обмежені
- Активують підписку на N днів без оплати
- Зберігаються в БД + JSON файлі

### Affiliate промокоди
- Знижка на перший платіж (N%)
- `regularAmount` = повна ціна (наступні без знижки)
- Комісія блогера: 20% від кожного платежу
- Відв'язка через 1 рік або при скасуванні

---

## 8. Адмін-панель

| Ендпоінт | Що робить |
|----------|-----------|
| GET /admin/api/users | Список юзерів з фільтрами |
| GET /admin/api/users/{id} | Деталі (payment info, card, recurring) |
| PUT /admin/api/users/{id} | Оновити статус/дату/символи |
| GET /admin/api/invoices | Всі чеки з фільтрацією |
| GET /admin/api/plans | Список планів |
| POST /admin/api/plans/create | Створити план |
| GET /admin/api/promo | Промокоди |

---

## 9. Відомі проблеми Voisio (НЕ повторювати в Imagio)

### 🔴 Критичні
1. **Два WayForPay клієнти** (wayforpay_api.py + wayforpay_payment.py) — дублювання коду
2. **recToken поле** — мертве, ніколи не використовується при regularMode
3. **Invoice в двох місцях** — metadata юзера + окрема таблиця
4. **Подвійний activate** — webhook + CHECK_STATUS обидва активують
5. **Синхронний sqlite3** — блокує event loop

### 🟡 Середні
6. **Webhook приймає все** навіть з невалідним підписом
7. **Немає handle_refunded** — повернення не обробляються
8. **Немає автоматичних тестів** для платіжної системи

---

## 10. Що взяти з Voisio в Imagio

### ✅ Архітектурні рішення
- Singleton WayForPay API клієнт
- Окремий subscription_manager для бізнес-логіки
- Каскадний пошук юзера при webhook
- regularMode = "monthly" для автопродовження
- Form-server pattern (GET /pay → auto-submit → WayForPay)
- Accept response завжди (інакше WFP стукає 4 доби)
- Retry count для declined (frozen → cancel)

### ❌ Що НЕ повторювати
- Дублювання API клієнтів
- Invoice в двох місцях (тільки окрема таблиця)
- Синхронний SQLite (Imagio вже async)
- recToken (не потрібен при regularMode)
- Приймання webhook без валідації підпису (хоча б логувати warning)
- Платіжні дані в user table (окрема таблиця)
