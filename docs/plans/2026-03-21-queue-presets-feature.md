# Queue + Presets + Feature Gating Implementation Plan

**Goal:** Додати чергу генерацій (batch), шаблони (presets) з БД-збереженням, систему доступу до фіч (feature gating), та concurrency-контроль API-задач.

**Architecture:** Нова таблиця `Preset` в БД. Нові FSM-стейти для черги та шаблонів. Семафори на рівні VoiceAPI pool для обмеження concurrency (3 задачі/ключ, 2 задачі/юзер). Feature enum для гейтингу підписок (зараз все дозволено, точка розширення на майбутнє).

**Tech Stack:** Python 3.11+, Aiogram 3 (FSM), SQLAlchemy async, SQLite, asyncio.Semaphore

---

## Task 1: Модель Preset в БД

**Files:**
- Modify: `app/db/models.py`
- Modify: `app/db/session.py` (якщо потрібен init_db)

**Steps:**

1.1. Додати модель `Preset` в `app/db/models.py`:

```python
class Preset(Base):
    __tablename__ = "presets"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    aspect_ratio: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    num_variants: Mapped[Optional[int]] = mapped_column(nullable=True)
    style_suffix: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="presets")
```

1.2. Додати relationship в `User`:
```python
presets: Mapped[List["Preset"]] = relationship(back_populates="user", cascade="all, delete-orphan")
```

1.3. Запустити: `python -c "from app.db.session import engine, Base; from app.db.models import *; import asyncio; asyncio.run(Base.metadata.create_all(bind=..))"`

**Commit:** `feat(db): add Preset model`

---

## Task 2: CRUD-сервіс для Presets

**Files:**
- Create: `app/services/presets.py`

**Steps:**

2.1. Створити `app/services/presets.py` з функціями:

```python
MAX_PRESETS_PER_USER = 10

async def get_active_preset(session, user_id) -> Preset | None
async def get_user_presets(session, user_id) -> list[Preset]
async def create_preset(session, user_id, name, aspect_ratio, num_variants, style_suffix) -> Preset
async def activate_preset(session, preset_id, user_id) -> Preset
async def deactivate_all_presets(session, user_id) -> None
async def delete_preset(session, preset_id, user_id) -> bool
async def update_preset(session, preset_id, user_id, **kwargs) -> Preset | None
async def count_user_presets(session, user_id) -> int
```

**Commit:** `feat(services): add presets CRUD service`

---

## Task 3: Feature Gating система

**Files:**
- Create: `app/services/feature_access.py`

**Steps:**

3.1. Створити `app/services/feature_access.py`:

```python
from enum import StrEnum

class Feature(StrEnum):
    GENERATE = "generate"
    EDIT = "edit"
    QUEUE = "queue"
    PRESETS = "presets"

# Mapping: tier → allowed features
TIER_FEATURES = {
    "free": {Feature.GENERATE},
    "basic": {Feature.GENERATE, Feature.EDIT},
    "pro": {Feature.GENERATE, Feature.EDIT, Feature.QUEUE, Feature.PRESETS},
}

async def check_feature_access(user_id: int, feature: Feature) -> bool:
    # TODO: look up user subscription tier from DB
    # For now: allow everything
    return True

async def get_user_tier(user_id: int) -> str:
    # TODO: query subscription
    return "pro"
```

**Commit:** `feat(services): add feature gating stub`

---

## Task 4: Concurrency-контроль в VoiceAPI pool

**Files:**
- Modify: `app/services/voiceapi.py`

**Steps:**

4.1. Додати семафори в `VoiceAPIPool`:

```python
MAX_CONCURRENT_PER_KEY = 3
MAX_CONCURRENT_PER_USER = 2

class VoiceAPIPool:
    def __init__(self, ...):
        ...
        self._key_semaphores: dict[str, asyncio.Semaphore] = {
            key: asyncio.Semaphore(MAX_CONCURRENT_PER_KEY) for key in api_keys
        }
        self._user_semaphores: dict[int, asyncio.Semaphore] = {}

    def _get_user_semaphore(self, user_id: int) -> asyncio.Semaphore:
        if user_id not in self._user_semaphores:
            self._user_semaphores[user_id] = asyncio.Semaphore(MAX_CONCURRENT_PER_USER)
        return self._user_semaphores[user_id]
```

4.2. Обгорнути `submit_generate` і `submit_edit` в `async with sem`:

```python
async def submit_generate(self, *, user_id: int = 0, **kwargs):
    user_sem = self._get_user_semaphore(user_id)
    async with user_sem:
        # existing round-robin logic, but also acquire key_sem
        for _ in range(len(self._keys)):
            key = self._next_key()
            key_sem = self._key_semaphores[key]
            async with key_sem:
                client = self._get_client(key)
                try:
                    result = await client.submit_generate(**kwargs)
                    return client, result
                except VoiceAPIRateLimitError:
                    continue
        raise VoiceAPIRateLimitError("All keys exhausted")
```

4.3. Оновити `generate_image_v2` і `edit_image_v2` щоб приймати `user_id`.

**Commit:** `feat(voiceapi): add concurrency semaphores per key and per user`

---

## Task 5: Локалізація нових повідомлень

**Files:**
- Modify: `bot/localization/messages.py`

**Steps:**

5.1. Додати ключі для черги, шаблонів, feature gating в MESSAGES для uk/en/es:

Ключі (uk-версія для прикладу):
```
"menu.queue": "📋 Черга генерацій"
"menu.presets": "⚙️ Шаблони"

"queue.intro_with_preset": "📋 Черга генерацій\nАктивний шаблон: «{name}» ({details})\n\nНадішли промпти, кожен з нового рядка ↵"
"queue.intro_no_preset": "📋 Черга генерацій\nШаблон не обрано — спочатку налаштуй параметри."
"queue.ratio_ask": "📐 Обери формат для всієї черги:"
"queue.variants_ask": "🔢 Скільки варіантів на кожен промпт?"
"queue.send_prompts": "✍️ Надішли промпти, кожен з нового рядка ↵"
"queue.added": "✅ Додано {count} промптів (всього: {total})"
"queue.limit_reached": "⚠️ Ліміт 25 промптів. Додано {added}, пропущено {skipped}."
"queue.prompt_too_long": "⚠️ Промпт #{number} занадто довгий (макс 4000 символів), пропущено."
"queue.empty": "📋 Черга порожня. Надішли промпти!"
"queue.progress": "🎨 Генерую {current}/{total}…"
"queue.item_done": "✅ Промпт {current}/{total} готово!"
"queue.all_done": "🎉 Черга завершена! Згенеровано {success}/{total} промптів."
"queue.item_failed": "❌ Промпт {current}/{total} не вдався: {error}"

"preset.menu_title": "⚙️ <b>Шаблони</b>"
"preset.active": "Активний: 🟢 {name} ({details})"
"preset.no_active": "Активний шаблон не обрано"
"preset.create": "📝 Створити новий"
"preset.list": "📋 Мої шаблони"
"preset.deactivate": "❌ Вимкнути шаблон"
"preset.back": "⬅️ Головне меню"
"preset.ask_name": "✏️ Назви шаблон:"
"preset.ask_ratio": "📐 Обери формат (або Пропустити):"
"preset.ask_variants": "🔢 Кількість варіантів (або Пропустити):"
"preset.ask_style": "🎨 Напиши стиль для промптів (або Пропустити):\n💡 <i>Наприклад: «in cyberpunk neon style, dark atmosphere»</i>"
"preset.created": "✅ Шаблон «{name}» створено та активовано!"
"preset.activated": "✅ Шаблон «{name}» активовано!"
"preset.deactivated": "✅ Шаблон вимкнено"
"preset.deleted": "🗑 Шаблон «{name}» видалено"
"preset.limit_reached": "⚠️ Ліміт 10 шаблонів. Видали непотрібні."
"preset.empty_list": "📋 У тебе ще немає шаблонів."
"preset.name_too_long": "⚠️ Назва занадто довга (макс 100 символів)."
"preset.confirm_delete": "Видалити шаблон «{name}»?"

"feature.locked": "🔒 Ця функція доступна з підпискою {tier} 💎"

"generate.with_preset": "🎨 Активний шаблон: «{name}» ({details})\n\nНадішли промпт — генерую з цими параметрами!"
```

**Commit:** `feat(i18n): add queue, preset, feature gating messages`

---

## Task 6: Клавіатури для черги та шаблонів

**Files:**
- Modify: `bot/keyboards/main_menu.py`

**Steps:**

6.1. Оновити `build_main_menu` — додати кнопки Queue та Presets.

6.2. Додати нові клавіатури:
```python
def build_queue_actions_keyboard(language: str) -> InlineKeyboardMarkup:
    # [➕ Додати ще]  [🚀 Запустити]  [🗑 Очистити]

def build_preset_menu_keyboard(language: str, active_name: str | None) -> InlineKeyboardMarkup:
    # [📝 Створити]  [📋 Мої шаблони]  [❌ Вимкнути]  [⬅️ Назад]

def build_preset_list_keyboard(presets: list, language: str) -> InlineKeyboardMarkup:
    # кнопка на кожен шаблон + [⬅️ Назад]

def build_preset_detail_keyboard(preset_id: int, language: str) -> InlineKeyboardMarkup:
    # [✅ Активувати]  [✏️ Редагувати]  [🗑 Видалити]  [⬅️ Назад]

def build_ratio_keyboard_with_skip(language: str) -> InlineKeyboardMarkup:
    # ratio buttons + [Пропустити]

def build_variant_keyboard_with_skip(language: str) -> InlineKeyboardMarkup:
    # 1-4 + [Пропустити]
```

**Commit:** `feat(keyboards): add queue and preset keyboards`

---

## Task 7: Хендлери шаблонів

**Files:**
- Create: `bot/handlers/presets.py`

**Steps:**

7.1. Створити FSM стейти:
```python
class PresetStates(StatesGroup):
    waiting_name = State()
    waiting_ratio = State()
    waiting_variants = State()
    waiting_style = State()
```

7.2. Хендлери:
- `menu:presets` callback → показати меню шаблонів
- `preset:create` → запитати назву
- `preset:list` → показати список шаблонів
- `preset:deactivate` → вимкнути активний шаблон
- `presetselect:{id}` → показати деталі шаблону
- `presetact:{id}` → активувати
- `presetdel:{id}` → видалити
- FSM хендлери для створення (name → ratio → variants → style → save)

**Commit:** `feat(handlers): add preset management handlers`

---

## Task 8: Хендлери черги генерацій

**Files:**
- Create: `bot/handlers/queue.py`

**Steps:**

8.1. FSM стейти:
```python
class QueueStates(StatesGroup):
    waiting_ratio = State()       # якщо немає шаблону
    waiting_variants = State()    # якщо немає шаблону
    waiting_prompts = State()     # чекаємо промпти
    running = State()             # генерація в процесі
```

8.2. Хендлери:
- `menu:queue` callback → перевірити feature access → перевірити активний шаблон → або міні-флоу ratio/variants, або одразу "кидай промпти"
- `waiting_prompts` message handler → парсити промпти через `\n`, валідувати (макс 25, макс 4000/промпт), зберегти в state, показати "Додано N (всього: M)" + кнопки
- `queue:add_more` → повернути в waiting_prompts
- `queue:run` → запустити генерацію по черзі
- `queue:clear` → очистити state

8.3. Логіка генерації черги:
```python
async def run_queue(message, state, prompts, ratio, num_variants, style_suffix, user_id, lang):
    total = len(prompts)
    success = 0
    for idx, prompt in enumerate(prompts, 1):
        full_prompt = f"{prompt}, {style_suffix}" if style_suffix else prompt
        status_msg = await message.answer(queue.progress {idx}/{total})
        try:
            result = await generate_image_v2(
                prompt=full_prompt, aspect_ratio=ratio,
                num_images=num_variants, user_id=user_id, ...
            )
            # send media group
            # delete status_msg
            success += 1
        except Exception:
            # send error for this prompt
            continue
    await message.answer(queue.all_done {success}/{total})
```

**Commit:** `feat(handlers): add queue generation handlers`

---

## Task 9: Оновити одиночну генерацію з урахуванням шаблону

**Files:**
- Modify: `bot/handlers/menu.py`

**Steps:**

9.1. В `handle_menu_callback` для action=="generate": перевірити активний шаблон.
- Якщо є → показати "Активний шаблон: X. Надішли промпт!"
- Якщо нема → як зараз (Студія)

9.2. В `handle_variant_choice`: додати style_suffix до промпта перед генерацією.

9.3. Додати `user_id` в виклики `generate_image_v2` і `edit_image_v2`.

**Commit:** `feat(handlers): integrate presets into single generation flow`

---

## Task 10: Реєстрація нових роутерів

**Files:**
- Modify: `bot/bot.py`
- Modify: `bot/handlers/__init__.py`

**Steps:**

10.1. Імпортувати і зареєструвати `bot.handlers.presets.router` і `bot.handlers.queue.router` в боті.

**Commit:** `feat(bot): register preset and queue routers`

---

## Task 11: Міграція БД

**Steps:**

11.1. Запустити скрипт створення таблиць.
11.2. Перевірити що таблиця `presets` створилась.

**Commit:** `chore(db): run migration for presets table`

---

## Task 12: Інтеграційна верифікація

**Steps:**

12.1. `python -c "from app.db.models import *; from app.services.presets import *; from app.services.feature_access import *; print('OK')"`
12.2. `python -c "from bot.handlers.presets import router; from bot.handlers.queue import router; print('OK')"`
12.3. Запустити бота, перевірити:
- /start → головне меню з новими кнопками
- Шаблони: створити, список, активувати, видалити
- Черга: кинути промпти, запустити
- Одиночна генерація з шаблоном

**Commit:** `test: verify integration of queue, presets, feature gating`
