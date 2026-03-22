# Imagio Voice Bot

Telegram бот з FastAPI backend для генерації зображень через VoiceAPI та отримання платних підписок через WayForPay.

## Стек
- FastAPI + Uvicorn
- SQLite + SQLAlchemy (async)
- Aiogram 3 для Telegram-бота
- HTTPX для звернень до VoiceAPI

## Швидкий старт
1. Створіть та активуйте віртуальне середовище Python 3.11+.
2. Встановіть залежності:
   ```bash
   pip install -r requirements.txt
   ```
3. Скопіюйте `.env.example` у `.env` та заповніть значення токенів/ключів.
4. Ініціалізуйте БД (виконується автоматично при старті FastAPI, але можна запустити `python scripts/start_server.py` один раз для створення таблиць).

## Запуск сервісів
- **FastAPI**: `python scripts/start_server.py`
- **Telegram-бот**: `python scripts/start_bot.py`

(Обидва процеси можна деплоїти окремо. На Railway FastAPI-додаток відповідатиме за вебхуки/оплати.)

## Структура
```
app/        # FastAPI, конфіги, БД, сервіси
bot/        # Aiogram-бот, хендлери, локалізація
scripts/    # Допоміжні раннери
```

## Локалізація
За замовчуванням бот відповідає українською. Користувач може перемкнутись на англійську або іспанську через пункт «Локалізація».

## Змінні середовища
- `TELEGRAM_BOT_TOKEN` — токен бота.
- `VOICE_API_BASE_URL`, `VOICE_API_KEY` — дані VoiceAPI.
- `DATABASE_URL` — шлях до SQLite (стандартно `sqlite+aiosqlite:///./data/app.db`).
- `ADMIN_IDS` — кома-сепарований список Telegram ID адмінів.
- `PROXY_URL` або набір `USE_PROXY`, `PROXY_HOST`, `PROXY_PORT`, `PROXY_USERNAME`, `PROXY_PASSWORD`, `PROXY_LIST` — параметри проксі для локальної розробки (у випадку логін/пароля адреса збирається автоматично).
- `WAYFORPAY_MERCHANT_ID`, `WAYFORPAY_SECRET` — інтеграція WayForPay.
- `WEBHOOK_BASE_URL` — майбутній публічний URL (Railway / інший хостинг).
- `BOT_DEFAULT_LANGUAGE` — `uk`, `en` або `es`.
- `LOG_LEVEL` — рівень логів (`INFO`, `DEBUG`, ...).

## Далі
- Реалізувати логіку генерації зображень через `VoiceAPIClient` у `app/services/voiceapi.py`.
- Прописати оплату WayForPay та зберігати статуси в таблиці `subscriptions`.
- Додати реальні відповіді на кнопки меню.
