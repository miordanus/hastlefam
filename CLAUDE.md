# CLAUDE.md — HastleFam Dev Reference

Telegram-first money copilot for a two-person household. FastAPI backend + aiogram Telegram bot, deployed on Railway, database on Supabase (PostgreSQL).

---

## Project layout

```
app/
  api/routers/        # FastAPI routes: health, tasks, finance, reviews
  application/        # Service layer: finance_service, jobs
  bot/
    handlers/         # capture.py, start.py, help.py
    middlewares/      # logging middleware
    main.py           # bot entry point (aiogram polling)
  domain/enums.py     # TransactionDirection, Currency, CategoryKind, etc.
  infrastructure/
    db/models/        # all_models.py — SQLAlchemy ORM classes
    db/session.py     # SessionLocal (lazy-loaded engine)
    config/settings.py
  dashboard/          # Jinja2 HTML templates
  main.py             # FastAPI app entry point
  seeds/              # seed_areas, seed_owners, seed_finance_categories
migrations/
  versions/           # 0001–0004 Alembic migration scripts
  manual_apply.sql    # hand-paste into Supabase SQL editor if needed
tests/
```

---

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | `postgresql+psycopg://...` (runtime, lazy-loaded) |
| `ALEMBIC_DATABASE_URL` | yes | same DSN used by alembic only |
| `TELEGRAM_BOT_TOKEN` | yes | BotFather token |
| `OPENAI_API_KEY` | yes | used by LLM draft service |
| `OPENAI_MODEL` | no | default `gpt-4.1-mini` |
| `REDIS_URL` | no | default `redis://localhost:6379/0` |
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

**Start command** (from `railway.json`):
```
python -m app.bot.main & uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Both the bot (polling) and the API server start from the same Railway service.
Health check hits `/health` with a 120 s timeout.

`Procfile` defines the same split for platforms that support multiple process types:
```
web:    uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: python -m app.bot.main
```

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
3. Run — it is idempotent (all migrations 0001–0004 combined)

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

## Telegram bot — user guide

### What the bot does

The bot is a fast, friction-free expense capture tool for a two-person household. Send a plain-text message and it logs the expense instantly. No menus, no forms.

### Getting started

1. Find the bot on Telegram (ask the admin for the bot username).
2. Send `/start` — you should see: `Money bot is online. Just send: "149 biedronka"`
3. If you see *"User not linked. Seed users table first."* your Telegram ID hasn't been added to the `users` table yet — tell the admin your Telegram numeric user ID.

### Commands

| Command | What it does |
|---|---|
| `/start` | Confirm the bot is alive |
| `/help` | Show command reference |
| `/month` | Month-to-date spend + income totals, top 3 categories, upcoming recurring till month end |
| `/upcoming` | Recurring payments due in the next 7 days |
| `/add <amount> <merchant>` | Explicit expense capture (useful if plain text capture doesn't trigger) |

### Quick expense capture (no command needed)

Just type the amount and merchant name separated by a space:

```
149 biedronka
49.90 netflix
8 coffee shop
```

Rules:
- Amount must be first, merchant must be at least 2 characters
- Commas and dots both work as decimal separators (`49,90` = `49.90`)
- Currency is saved as USD by default (multi-currency support is planned)
- Duplicate detection: if the same amount + merchant is sent twice on the same day, the second message is silently dropped with `"Looks like duplicate, skipped."`
- Confidence threshold: merchant names shorter than 3 characters are flagged low-confidence and rejected

### What gets saved

Each captured expense creates a `Transaction` row:
- `direction = expense`
- `amount` and `currency` from the parsed text
- `merchant_raw` = the merchant string
- `source = "telegram"`
- `parse_status = "ok"`
- `occurred_at` = UTC timestamp of the message
- `dedup_fingerprint` = SHA-256 of `household_id|date|amount|merchant|telegram`

### Monthly summary (`/month`)

Returns a single message with:
```
MTD spend: 1234.50
MTD income: 5000.00
Top categories:
• groceries: 320.00
• subscriptions: 149.00
• transport: 98.00
Upcoming till month end:
• 2026-03-20 Netflix 49.90 USD
• 2026-03-28 Rent 2200.00 USD
```

### Upcoming payments (`/upcoming`)

Lists recurring payments due in the next 7 days:
```
Upcoming (7d):
• 2026-03-15 | Spotify | 9.99 USD
• 2026-03-18 | Phone plan | 35.00 USD
```

### Troubleshooting

| Message | Cause | Fix |
|---|---|---|
| `User not linked. Seed users table first.` | Your Telegram numeric ID is not in `users.telegram_id` | Admin runs seeds or manually inserts your user row |
| `Looks like duplicate, skipped.` | Same amount+merchant sent twice today | Intentional — check transactions if needed |
| `Not confident enough to save. Try format: 149 biedronka` | Merchant name too short | Use a longer merchant name |
| Bot doesn't respond at all | Bot process not running | Check Railway logs; redeploy if needed |

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
| `TransactionDirection` | `expense`, `income` |
| `Currency` | `USD`, `PLN`, `EUR` |
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

Test suite covers: finance service, import pipeline, dedup fingerprint logic, API health endpoint.

---

## Key decisions / constraints

- **No LLM for core finance logic** — categorization is rule-based; LLM drafts are a separate optional layer.
- **No bank integrations** — SQL import is the only ingest path.
- **No goals/forecasting** — out of scope for this MVP.
- **Two-process deployment** — bot (polling) and API run in the same Railway service via `&`.
- **Supabase enums are lowercase** — always use `values_callable=_enum_values` on any new `Enum()` column.
