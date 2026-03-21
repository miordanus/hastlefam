# CLAUDE.md — HastleFam Dev Reference

Telegram-first money copilot for a two-person household. FastAPI backend + aiogram Telegram bot, deployed on Railway, database on Supabase (PostgreSQL).

---

## Project layout

```
app/
  api/routers/        # FastAPI routes: health, tasks, finance, reviews
  application/
    services/         # finance_service.py, fx_service.py, autocat_service.py,
                      # insights_service.py, ask_service.py, import_service.py,
                      # llm_service.py, users_service.py, tasks_service.py
    jobs/             # daily_status_job.py (apscheduler, 10:00 MSK)
  bot/
    handlers/         # capture.py, start.py, help.py, month.py, upcoming.py,
                      # balances.py, inbox.py, exchange_handler.py,
                      # duplicate_handler.py, inline_actions.py, cancel.py,
                      # ask.py, rules.py
    middlewares/      # logging middleware, idempotency.py (Redis dedup)
    parsers/          # expense_parser.py — pure deterministic parser
    main.py           # bot entry point (aiogram polling + Redis lock)
  domain/enums.py     # TransactionDirection, Currency, CategoryKind, etc.
  infrastructure/
    db/models/        # all_models.py — SQLAlchemy ORM classes
    db/session.py     # SessionLocal (lazy-loaded, @lru_cache factory)
    config/settings.py
  dashboard/          # Jinja2 HTML templates
  main.py             # FastAPI app entry point
  seeds/              # seed_areas, seed_owners, seed_finance_categories
migrations/
  versions/           # 0001–0010+ Alembic migration scripts
  manual_apply.sql    # hand-paste into Supabase SQL editor if needed
tests/
```

---

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | `postgresql+psycopg://...` (runtime, lazy-loaded) |
| `ALEMBIC_DATABASE_URL` | yes | same DSN used by alembic only |
| `TELEGRAM_BOT_TOKEN` | **worker only** | BotFather token — optional for web service |
| `OPENAI_API_KEY` | yes | used by LLM draft service |
| `OPENAI_MODEL` | no | default `gpt-4.1-mini` |
| `REDIS_URL` | no | default `redis://localhost:6379/0`; if absent, bot degrades gracefully (no lock/idempotency) |
| `APP_ENV` | no | default `local` |
| `LOG_LEVEL` | no | default `INFO` |

Copy `.env.example` → `.env` and fill in real values before running locally.

---

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
cp .env.example .env          # fill in DATABASE_URL, TELEGRAM_BOT_TOKEN, etc.
alembic upgrade head
python -m app.seeds.run_all

# run both processes (separate terminals or tmux)
uvicorn app.main:app --reload
python -m app.bot.main
```

---

## Deployment (Railway)

Two separate Railway services, each using `Procfile`:

```
web:    uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: python -m app.bot.main
```

- `railway.json` has **no `startCommand`** — Railway falls back to Procfile per service.
- Web service (`Web-AYHO`) runs uvicorn only; `TELEGRAM_BOT_TOKEN` is not required there.
- Worker service (`Worker-H5P8`) runs the bot only; `PORT` is not required there.
- Health check hits `/health` with a 120 s timeout (web service only).

---

## Database migrations (Alembic)

```bash
# apply all migrations
alembic upgrade head

# generate a new one
alembic revision --autogenerate -m "description"

# rollback one step
alembic downgrade -1
```

If `alembic` can't reach the remote Supabase DB (e.g. from a local network), use the prebuilt SQL script:

1. Open Supabase → SQL Editor
2. Paste `migrations/manual_apply.sql`
3. Run — it is idempotent (all migrations combined)

---

## Fix log — 2026-03-13

### Fix 1 — `python-multipart` missing from `pyproject.toml` (PR #16)
**Symptom:** Vercel deploy crashed on import because `python-multipart` was listed in `requirements.txt` but not in `pyproject.toml`.
**Fix:** Added `python-multipart>=0.0.6` to `[project].dependencies` in `pyproject.toml`.
**File:** `pyproject.toml`

### Fix 2 — Telegram bot not starting on Railway (PR #17)
**Symptom:** Only `uvicorn` was starting; the bot process was never launched so the bot never polled Telegram.
**Root cause:** `railway.json` had only the uvicorn command as the start command.
**Fix:** Updated `railway.json` to run both processes:
```
python -m app.bot.main & uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```
**File:** `railway.json`

### Fix 3 — SQLAlchemy Enum sending uppercase names to PostgreSQL (PR #18)
**Symptom:** Every write to an enum column failed with:
```
invalid input value for enum transaction_direction_enum: "EXPENSE"
```
**Root cause:** SQLAlchemy's `Enum()` defaults to sending Python member *names* (`EXPENSE`, `INCOME`) but the PostgreSQL enum types were created with lowercase *values* (`expense`, `income`).
**Fix:** Added `values_callable=_enum_values` to every `Enum(...)` column definition in `all_models.py`, where `_enum_values` returns `[e.value for e in enum_cls]`.
**Affected columns:** `Transaction.direction`, `Transaction.currency`, `Account.currency`, `RecurringPayment.currency`, `SavingsGoal.currency`, `FinanceCategory.kind`, `Task.task_type`, `Task.status`, `Note.note_type`, `Meeting.meeting_type`, `LLMDraft.draft_type`.
**File:** `app/infrastructure/db/models/all_models.py`

---

## Fix log — 2026-03-14

### Fix 4 — Bot startup crash: missing packages in `requirements.txt` (PR #23)
**Symptom:** Bot crashed at import with `ModuleNotFoundError: No module named 'redis'` because Railway installs from `requirements.txt`, not `pyproject.toml`.
**Fix:** Synced `requirements.txt` with `pyproject.toml`: added `redis>=5.0`, `apscheduler>=3.10`, `psycopg-binary`. Both files are the source of truth going forward.
**Files:** `requirements.txt`

### Fix 5 — Duplicate bot instances causing TelegramConflictError (PR #23)
**Symptom:** During Railway deployment overlap, two bot instances polled simultaneously, causing a flood of `TelegramConflictError`.
**Fix:** Added a Redis distributed lock in `bot/main.py` — only one instance polls at a time; a second instance exits with a WARNING. Also added `IdempotencyMiddleware` (Redis key per `chat_id+message_id`, 5-min TTL) to drop duplicate Telegram update deliveries silently.
**Files:** `app/bot/main.py`, `app/bot/middlewares/idempotency.py`

### Fix 6 — Both Railway services running bot+uvicorn (PR #32)
**Symptom:** Both Web and Worker services were executing the combined `bot & uvicorn` command (from `railway.json startCommand`), running two bot instances and silencing bot logs via backgrounding.
**Fix:** Removed `startCommand` from `railway.json`. Railway now falls back to `Procfile`: web→uvicorn only, worker→bot only.
**Files:** `railway.json`

### Fix 7 — Web service crashing because `TELEGRAM_BOT_TOKEN` is required (PR #33)
**Symptom:** `ValidationError` at import time on the web service where the bot token env var is absent, crashing uvicorn before it could serve any requests.
**Fix:** Made `TELEGRAM_BOT_TOKEN` optional in `settings.py` (only the worker needs it).
**File:** `app/infrastructure/config/settings.py`

### Fix 8 — aiogram `dp.routers` AttributeError crashing bot startup (PR #26)
**Symptom:** Bot process crashed immediately after scheduler start, before polling was reached.
**Root cause:** aiogram 3's `Dispatcher` has no public `.routers` attribute.
**Fix:** Removed the invalid attribute access; startup log now counts registered routers differently.
**File:** `app/bot/main.py`

### Fix 9 — FSM/capture routing conflicts (PR #27)
**Symptom:** Users stuck in FSM states (balance editing, tag input) with no escape; all subsequent messages intercepted by state handlers, making the bot appear broken.
**Fix:** Added `/cancel` command (registered first) to escape any active FSM state. Added `/cancel` hints to all FSM prompts. Added dedup fingerprint check before saving. Fixed direction included in dedup fingerprint so income+expense with same amount+merchant+date are not treated as duplicates.
**Files:** `app/bot/handlers/cancel.py`, `app/bot/handlers/capture.py`, and others.

---

## Fix log — 2026-03-15 to 2026-03-21

### Fix 10 — `bot/main.py` exits cleanly when `TELEGRAM_BOT_TOKEN` is not set (PR #35)
**Symptom:** Worker service would crash with a confusing traceback if run without a bot token.
**Fix:** Added an early guard in `bot/main.py` — exits with a clear WARNING if `TELEGRAM_BOT_TOKEN` is absent.
**File:** `app/bot/main.py`

### Fix 11 — Handler visibility, connection pool, error logging (PR #35)
**Symptom:** Some handlers were not responding; database connection pool exhausted under load; errors swallowed silently.
**Fix:** Re-registered all routers explicitly; tuned SQLAlchemy pool settings; added structured error logging.
**Files:** `app/bot/main.py`, `app/infrastructure/db/session.py`

### Fix 12 — `TelegramConflictError` — immediate exit + Redis lock released first (PR #37, #39)
**Symptom:** On Railway deployment overlap, `TelegramConflictError` flooded logs; old instance held Redis lock for full TTL (60 s) before releasing, delaying restart.
**Fix:** Bot now calls `_release_global_lock()` (best-effort Redis lock release) immediately before `os._exit(1)` on conflict. Suppressed APScheduler noise in logs.
**File:** `app/bot/main.py`

### Fix 13 — Railway healthcheck killing Worker service (PR #38)
**Symptom:** Railway's healthcheck (configured in `railway.json`) was probing the Worker service, which has no HTTP port, and marking it unhealthy → restart loop.
**Fix:** Removed the healthcheck entry from `railway.json` entirely. Healthcheck only applies to the web service via Procfile/Railway UI.
**File:** `railway.json`

### Fix 14 — Broken seed runner + missing user seeding (PR #40)
**Symptom:** `python -m app.seeds.run_all` crashed; user rows were not seeded, causing "User not linked" errors on first bot use.
**Fix:** Fixed seed runner import order and added explicit user seeding step.
**Files:** `app/seeds/`

### Fix 15 — `httpx` missing from `requirements.txt` (PR #41)
**Symptom:** Bot crashed at import with `ModuleNotFoundError: No module named 'httpx'` because `httpx` (needed by `fx_service.py`) was not in `requirements.txt`.
**Fix:** Added `httpx>=0.27` to `requirements.txt`.
**File:** `requirements.txt`

### Fix 16 — Stale Redis poller lock — wait up to 70 s instead of exiting (PR #44)
**Symptom:** On Railway cold start, if a previous instance's lock hadn't expired yet (TTL 60 s), the new instance exited immediately with "lock not acquired", leaving the bot silent until the next restart.
**Fix:** Changed `lock.acquire()` to `blocking=True, blocking_timeout=70` — the new instance waits up to 70 s for the stale lock to expire before giving up.
**File:** `app/bot/main.py`

---

## Telegram bot — user guide

### What the bot does

The bot is a fast, friction-free expense capture tool for a two-person household. Send a plain-text message and it logs the expense instantly. All user-facing text is Russian.

### Getting started

1. Find the bot on Telegram (ask the admin for the bot username).
2. Send `/start` — you should see the welcome message in Russian.
3. If you see *"User not linked. Seed users table first."* your Telegram ID hasn't been added to the `users` table yet — tell the admin your Telegram numeric user ID.

### Commands

| Command | What it does |
|---|---|
| `/start` | Confirm the bot is alive; show onboarding hint |
| `/help` | Show command reference (Russian) |
| `/month [month]` | Month-to-date spend + income per currency, top tags, inline prev/next navigation. Optional arg: `/month 2` or `/month 2026-02` |
| `/upcoming` | All future transactions (occurred_at > today, excludes TRANSFER/EXCHANGE) |
| `/balances` | Manual balance log: view accounts, update snapshots, add new accounts |
| `/inbox` | Unresolved untagged transactions — quick-tag + delete flow with inline buttons |
| `/ask <question>` | Natural-language finance query answered by OpenAI (Russian) |
| `/rules` | List, add, or delete auto-categorization merchant→tag rules |
| `/cancel` | Exit any active FSM state (balance edit, tag input, exchange flow, etc.) |

### Quick expense capture (no command needed)

Just type the amount and merchant name:

```
149 biedronka
49.90 netflix #еда
+8000 зарплата
100 USD кофе
200₽ аптека
обмен 1000 USD → RUB по 90
```

Rules:
- Amount must be first; merchant must be at least 2 characters
- Commas and dots both work as decimal separators (`49,90` = `49.90`)
- **Default currency is RUB** (not USD)
- Currency can be specified inline: `100 USD кофе`, `200₽ аптека`
- Income requires explicit `+` prefix: `+8000 зарплата`
- Tags parsed from `#tag` syntax; `primary_tag` + `extra_tags` stored separately
- Duplicate detection: if the same amount + merchant + direction is sent twice on the same day, user gets a **confirmation dialog** (inline buttons) instead of a silent drop
- Confidence threshold: merchant names shorter than 3 characters are flagged low-confidence and rejected
- Date hints accepted inline: `вчера`, `позавчера`, `DD-MM`, `DD.MM`, `DD/MM`, `YYYY-MM-DD`
- Exchange syntax: `обмен <amount> <from_currency> → <to_currency> по <rate>` triggers FSM flow

### Post-capture inline actions

After each capture, relevant inline buttons appear:
- **Дата** — correct the transaction date
- **Тег** — add/change the tag
- **Валюта** — change currency

### What gets saved

Each captured expense creates a `Transaction` row:
- `direction` — `expense` / `income` / `exchange`
- `amount` and `currency` from the parsed text
- `primary_tag` — first `#tag` from message
- `extra_tags` — remaining tags (JSONB)
- `merchant_raw` = the merchant string
- `source = "telegram"`
- `parse_status = "ok"`
- `occurred_at` = UTC timestamp (or parsed date hint)
- `dedup_fingerprint` = SHA-256 of `household_id|date|amount|merchant|direction|telegram`

### Monthly summary (`/month`)

Returns a message with inline prev/next navigation:
```
Март 2026

Расходы: 1 234 ₽ | 49 $
Доходы: 5 000 ₽
Без тега: 3

Топ теги:
• продукты: 320 ₽
• подписки: 49 $
• транспорт: 98 ₽

[🏷 Разобрать (3)]  [💡 Инсайты]  [💼 Балансы]
[◀ Февраль]                        [Апрель ▶]
```

- EXCHANGE transactions are excluded from spend/income totals.
- **💡 Инсайты** button calls `insights_service.py` — OpenAI generates MoM comparisons, anomaly callouts, and actionable recommendations in Russian.
- Amounts formatted with space thousands separator and currency symbol.

### Upcoming payments (`/upcoming`)

Lists all future transactions (no 7-day limit):
```
Предстоящие платежи:
• 2026-03-20 | Netflix | 49.90 USD
• 2026-03-28 | Аренда | 2200.00 RUB
```

### Balance log (`/balances`)

Shows household accounts with latest snapshot + date. Inline actions per account:
- **✏️ Обновить** — enter new balance; delta vs previous is shown (converted to RUB using FX rates) and logged as a `balance_adjustment` transaction
- **➕ Добавить счёт** — self-serve flow: name → currency → first balance

### Inbox (`/inbox`)

Untagged transactions shown one at a time:
- Quick-tag buttons from household's top-4 existing tags
- **✏️ Свой тег** — FSM for custom tag input
- **⏭ Пропустить** — advance to next
- **🗑 Удалить** — permanently delete the transaction

### Natural-language queries (`/ask`)

`/ask сколько потратил на кафе за 3 месяца?` — sends a structured prompt with relevant finance data to OpenAI and returns an answer in Russian. Degrades gracefully if OpenAI is unavailable.

### Auto-categorization rules (`/rules`)

Rules map merchant patterns to tags (case-insensitive, per-household):
- **Auto-learn:** when the same merchant is tagged identically 3+ times, a rule is created automatically.
- **Manual:** `/rules кофейня кафе` — create/update rule; `/rules удалить кофейня` — delete.
- `/rules` with no args lists all active rules with source (`🤖` auto / `✏️` manual) and hit count.

### Exchange flow

Send `обмен 1000 USD → RUB по 90` (or similar syntax):
- If accounts match 1:1 by currency → immediate confirm with balance note
- If ambiguous (multiple accounts same currency) → FSM picker
- On confirm: creates `Transaction` with `direction=exchange`, updates `BalanceSnapshot` on both accounts

### FX rates

`fx_service.py` fetches daily rates from the Central Bank of Russia (CBR XML feed) for USD, EUR, PLN → RUB. Rates are stored in the `fx_rates` table. `convert_to_rub()` is used by `/balances` and `/month` for cross-currency totals. No API key required. Degrades gracefully on network failure.

### Daily status job

`apscheduler` fires at 10:00 MSK every day: sends a brief household summary to configured chat(s). Also triggers `fetch_and_store_rates()` to refresh FX data.

### Troubleshooting

| Message | Cause | Fix |
|---|---|---|
| `User not linked. Seed users table first.` | Your Telegram numeric ID is not in `users.telegram_id` | Admin runs seeds or manually inserts your user row |
| Duplicate confirmation dialog | Same amount+merchant+direction sent twice today | Confirm to save or dismiss |
| `Not confident enough to save. Try format: 149 biedronka` | Merchant name too short | Use a longer merchant name |
| Bot doesn't respond at all | Bot process not running | Check Railway Worker logs; redeploy if needed |
| Stuck in a flow / bot ignores messages | Active FSM state | Send `/cancel` |

---

## API routes (reference)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check (used by Railway) |
| GET | `/` | HTML dashboard (Jinja2) |
| GET/POST | `/finance/...` | Transaction CRUD, SQL import, summaries |
| GET/POST | `/tasks/...` | Task management (frozen for MVP) |
| GET/POST | `/reviews/...` | Review screen for uncategorized transactions |

### SQL import endpoint

```http
POST /finance/import/sql
Content-Type: application/json

{
  "query": "SELECT ...",
  "source_name": "revolut",
  "owner_slug": "mine"
}
```

Flow: raw row → `raw_import_transactions` → normalized `transactions` with dedup.
Rows that can't be categorized are saved with `parse_status=needs_correction`.

---

## Domain enums

| Enum | Values |
|---|---|
| `TransactionDirection` | `expense`, `income`, `exchange` |
| `Currency` | `USD`, `PLN`, `EUR`, `RUB` |
| `CategoryKind` | `expense`, `income`, `transfer` |
| `TaskStatus` | `backlog`, `todo`, `in_progress`, `done`, `cancelled` |
| `TaskType` | `task`, `chore`, `project` |

All enums are stored by **value** (lowercase) in PostgreSQL — not by name.

---

## Seeds

```bash
python -m app.seeds.run_all
```

Creates default: household, two users (mine + wife), owners, areas, finance categories.
User `telegram_id` values must match real Telegram numeric IDs — edit seed files before running in production.

---

## Tests

```bash
pytest
# or with coverage
pytest --tb=short -q
```

Test suite covers: finance service (including EXCHANGE exclusion, untagged counts), import pipeline, dedup fingerprint logic, API health endpoint, expense parser (21 parser tests).

---

## Key decisions / constraints

- **No LLM for core finance logic** — categorization is rule-based via `autocat_service.py`; LLM is used only for insights (`insights_service.py`) and `/ask` queries.
- **No bank integrations** — SQL import is the only ingest path.
- **No goals/forecasting** — out of scope for this MVP.
- **Strict two-service deployment** — web (uvicorn) and worker (bot) are separate Railway services via Procfile; `railway.json` has no `startCommand` and no healthcheck entry.
- **Supabase enums are lowercase** — always use `values_callable=_enum_values` on any new `Enum()` column.
- **Default currency is RUB** — not USD; multi-currency is supported inline.
- **Redis is optional** — bot starts and polls without it; distributed lock and idempotency middleware degrade gracefully. Lock is released before `os._exit` on `TelegramConflictError`.
- **Redis lock blocks on startup** — new bot instance waits up to 70 s for a stale lock to expire (`blocking_timeout=70`) rather than exiting immediately.
- **EXCHANGE excluded from financial totals** — `/month` spend/income never includes exchange transactions.
- **FX rates from CBR** — daily XML feed, no API key, stored in `fx_rates` table; used for RUB conversions in balances and monthly totals.
- **Auto-cat rules** — `MerchantTagRule` table, per-household, auto-learned at threshold=3 tags, also manually manageable via `/rules`.
