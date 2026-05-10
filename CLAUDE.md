# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Telegram-first money copilot for a two-person household. FastAPI backend + aiogram 3 Telegram bot, deployed on Railway (two separate services), database on Supabase (PostgreSQL, schema `hastlefam`). A Vercel adapter (`api/index.py` → `app.main:app`) is also configured for the web service.

Python 3.11 only (`runtime.txt`).

---

## Project layout

```
app/
  main.py                       # FastAPI app (web service entrypoint)
  bot/
    main.py                     # aiogram polling bot (worker entrypoint)
    draft_store.py              # Redis-backed draft cache (duplicate confirm flow)
    handlers/                   # one router per concern; capture.py is the catch-all
    middlewares/                # logging.py, idempotency.py
    parsers/                    # debt_parser, split_parser, expense_parser
  api/
    deps.py                     # get_db dependency
    routers/                    # health, tasks, finance, reviews
    schemas/                    # pydantic request/response models
  application/
    services/                   # ask, autocat, budget, finance, fx, import,
                                # insights, llm, meetings, tasks, users
    jobs/                       # daily_status_job, recurring_reminders (APScheduler)
    dto/                        # llm_contracts
  domain/
    enums.py                    # all StrEnum types (single source of truth)
  infrastructure/
    config/settings.py          # pydantic-settings; loads from .env
    db/
      base.py                   # DB_SCHEMA = 'hastlefam', DeclarativeBase
      session.py                # SessionLocal context manager + engine
      models/all_models.py      # all 26 ORM models in one file
    llm/                        # OpenAI provider, contracts, validators
    logging/logger.py           # structlog JSON config
    repositories/               # base repository helpers
  observability/
    error_handler.py            # FastAPI 500 handler
    event_logger.py             # writes to event_log table
    prompt_logger.py            # LLM prompt/response logging
  dashboard/templates/          # Jinja2: index.html, finance_corrections.html
  seeds/                        # run_all + seed_{areas,categories,owners,users}
api/index.py                    # Vercel adapter (re-exports FastAPI app)
migrations/                     # alembic env + 0001..0020 versions + manual_apply.sql
tests/                          # pytest, SQLite in-memory via conftest.py
Procfile                        # web: uvicorn ; worker: python -m app.bot.main
```

---

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
cp .env.example .env   # fill DATABASE_URL, TELEGRAM_BOT_TOKEN, OPENAI_API_KEY

# Database
alembic upgrade head
python -m app.seeds.run_all

# Run (two separate terminals)
uvicorn app.main:app --reload
python -m app.bot.main

# Tests
pytest
pytest tests/test_capture.py          # single file
pytest -k "test_parse_amount"         # single test by name
pytest --tb=short -q                  # terse output
```

Tests use SQLite in-memory (no real DB needed). `conftest.py` sets dummy env vars before any app import so `Settings()` doesn't crash. The `db` fixture strips the `hastlefam` schema from `Base.metadata` (SQLite has no schemas) and restores it after teardown — keep this in mind when adding tests that touch new tables.

---

## Architecture

### Two processes, one codebase

**Web** (`app/main.py`) — FastAPI + Jinja2 dashboard at `/`, plus routers under `/finance`, `/tasks`, `/reviews`, `/health`. No bot logic, `TELEGRAM_BOT_TOKEN` not required.  
**Worker** (`app/bot/main.py`) — aiogram 3 polling bot + APScheduler (daily status digest at 10:00 MSK, recurring payment reminders). No HTTP port. Fetches FX rates on startup.  
Railway `Procfile` maps `web:` → uvicorn, `worker:` → bot. `railway.json` has no `startCommand` and no healthcheck entry. `vercel.json` routes everything to `api/index.py` which re-exports the FastAPI app — deploy the web service to either platform.

### Request flow: Telegram message → DB

1. `bot/main.py` polls Telegram; `LoggingMiddleware` runs first, then `IdempotencyMiddleware` (Redis dedup by `chat_id+message_id`).
2. Routers are registered in priority order: `cancel` → command handlers → `exchange_router` → `inline_actions_router` → `duplicate_router` → ... → `capture_router` (catch-all last).
3. `capture.py` dispatches to: `debt_parser` → `split_parser` → `expense_parser` (in that order; first match wins).
4. After parsing, `autocat_service.lookup_tag()` applies merchant→tag rules; `finance_service` or direct DB write saves the `Transaction`.
5. Post-capture inline keyboard (date / tag / currency correction) is built by `inline_actions.build_post_capture_keyboard()`.

### Bot routers / commands

Routers are registered in this exact order in `bot/main.py` (cancel first, capture last):

`cancel` → `start` → `help` → `month` → `upcoming` → `exchange` → `inline_actions` → `duplicate` → `inbox` → `balances` → `rules` → `ask` → `budgets` → `debts` → `cashflow` → `review` → `recurring` → `capture`

User-facing commands implemented across these handlers include `/start`, `/help`, `/month`, `/upcoming`, `/inbox`, `/balances`, `/rules`, `/ask`, `/budgets`, `/debts`, `/cashflow`, `/review`, `/recurring`, `/add`, `/cancel`. Anything not matched by a command falls through to `capture.py` (the `@router.message()` catch-all).

### Database layer

All 26 ORM models live in `app/infrastructure/db/models/all_models.py` (single file): `Household, User, Owner, Area, Sprint, Task, Decision, Note, Meeting, FinanceCategory, Account, RawImportTransaction, Transaction, RecurringPayment, SavingsGoal, Reminder, Digest, LLMDraft, PlannedPayment, BalanceSnapshot, EventLog, MerchantTagRule, Debt, CategoryBudget, TagBudget, FxRate`.

All tables live in the `hastlefam` Postgres schema (set via `connect_args={'options': '-csearch_path=hastlefam'}` in `session.py`; constant `DB_SCHEMA = 'hastlefam'` in `db/base.py`).

**Critical pattern — SQLAlchemy enums:** Every `Enum(...)` column **must** use `values_callable=_enum_values` to send lowercase values to PostgreSQL. Postgres enums are created with lowercase values; SQLAlchemy defaults to sending Python member *names* (uppercase), which causes `invalid input value for enum` errors.

**Session pattern:** Use `with SessionLocal() as db:` (context manager) everywhere. FastAPI routes use `Depends(get_db)` from `app/api/deps.py`.

### Financial invariants (ЗАКОН)

These rules must be respected in every query that touches transactions:

- `is_planned=True` → never counted as actual income/expense (future planned payments only).
- `is_internal_transfer=True` → never counted as income/expense (intra-household fund movement).
- `direction=EXCHANGE` → excluded from spend/income totals.
- Every new query for actual spend/income must filter `is_planned == False` AND `is_internal_transfer == False`.

### Parsers (pure, no side effects)

Three deterministic parsers in `app/bot/parsers/`, each returning a dataclass or `None`:

| Parser | Trigger | Returns |
|---|---|---|
| `debt_parser.py` | `дал 500 Васе` / `взял 1000 у Пети` | `DebtParseResult` |
| `split_parser.py` | `700 еда 13.03-19.03` (date range) | `SplitParseResult` |
| `expense_parser.py` | everything else | `ParseResult` |

`expense_parser` default currency is **RUB**. Income requires explicit `+` prefix. Tags parsed from `#word` syntax (always lowercased before storage so `TagBudget` matching works).

### LLM usage (narrow scope)

LLM is used only for:
- `insights_service.py` — OpenAI MoM comparison + anomaly callouts (enabled by `INSIGHTS_ENABLED=true`).
- `ask_service.py` — `/ask` natural-language query.
- `llm_service.py` — structured JSON generation via `OpenAIProvider.generate_json()`.

Core finance logic (categorization, parsing, summaries) is entirely rule-based. No LLM in the transaction capture path.

### FX rates

`fx_service.py` fetches daily rates from CBR XML feed (no API key, windows-1251 encoded). Rates stored as `1 foreign_currency = X RUB`. `convert_to_rub()` falls back up to 7 days if today's rate is missing. CBR-tracked codes: USD, EUR, PLN, AMD; USDT is upserted using the USD rate as a proxy. The `Currency` enum itself is `RUB, USD, USDT, EUR, AMD` — PLN has FX rates but is not in the enum.

### Auto-categorization rules

`autocat_service.py` — per-household `merchant_tag_rules` table. Auto-learned after 3 identical merchant+tag combinations. `/rules` command manages rules manually. Merchant matching is case-insensitive, full-string (not substring).

### Redis (optional)

Bot starts without Redis. When available it provides three things:
1. Distributed polling lock (`hastlefam:bot:poller`, TTL 60s, renewed every 20s) prevents two instances polling simultaneously. On `TelegramConflictError`, lock is released before `os._exit(1)` so Railway can restart cleanly. New instance waits up to 70s for stale lock to expire.
2. `IdempotencyMiddleware` — dedupes Telegram updates by `chat_id+message_id`. Only registered when Redis connected.
3. `draft_store` — short-lived draft cache used by the duplicate-confirmation flow in `capture.py`.

### Observability

- Structured JSON logs via `structlog` (`app/infrastructure/logging/logger.py`).
- `event_log` DB table for domain events via `observability/event_logger.py`.
- `observability/prompt_logger.py` for LLM prompt/response logging.

### OpenClaw agent (external, Supabase-direct) — MVP/agent mode

Openclaw is an external AI agent (already live, wired to the Telegram bot via Whisper STT) operating in **MVP/agent mode**: it bypasses the FastAPI layer entirely and speaks the Supabase REST API directly using `SUPABASE_SERVICE_ROLE_KEY`. This is intentional, not a gap.

**Data flow:** Telegram voice → Whisper STT → OpenClaw → Supabase REST (no FastAPI in this path)

Two capabilities:
1. **Mass-add transactions from voice** — transcription (Whisper) → parse items → full preview → user confirmation → bulk `POST /transactions`.
2. **AI finance advisor** — natural-language finance questions → fetch + aggregate transactions via REST → answer.

Openclaw targets the `hastlefam` schema via `Accept-Profile: hastlefam` (reads) and `Content-Profile: hastlefam` (writes) headers.

Full instructions + operational contract: `docs/openclaw-agent-instructions.md` (loaded as Openclaw's system prompt). No new code or migrations were needed — the schema was already complete.

---

## Key conventions

- **All user-facing text is Russian.**
- **All enums extend `StrEnum`** — values are lowercase strings stored directly in Postgres.
- **New `Enum()` columns** always need `values_callable=_enum_values`.
- **New DB tables** go in `all_models.py`, then generate migration: `alembic revision --autogenerate -m "description"`.
- **Handler router order matters** — `cancel` first, `capture_router` (catch-all `@router.message()`) last.
- **FSM states** — all FSM flows must have `/cancel` escape; always add `/cancel` hint to prompts.
- **Tags** — always lowercased before storage (see `expense_parser.py` lines 140–141).
- **`dedup_fingerprint`** — SHA-256 of `household_id|date|amount|currency|merchant|direction|telegram`; direction is included so income+expense with same amount+merchant are not treated as duplicates.

---

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | `postgresql+psycopg://...` |
| `ALEMBIC_DATABASE_URL` | yes | same DSN, used by alembic only |
| `TELEGRAM_BOT_TOKEN` | worker only | optional for web service |
| `OPENAI_API_KEY` | yes | LLM features |
| `OPENAI_MODEL` | no | default `gpt-4.1-mini` |
| `REDIS_URL` | no | default `redis://localhost:6379/0` |
| `INSIGHTS_ENABLED` | no | default `false`; enables OpenAI insights |
| `SUPABASE_URL` | OpenClaw only | Supabase project URL, e.g. `https://<ref>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | OpenClaw only | Service role key for OpenClaw direct Supabase access — not used by FastAPI/bot |
| `APP_ENV` | no | default `local` |
| `LOG_LEVEL` | no | default `INFO` |

---

## Migrations

```bash
alembic upgrade head                            # apply all
alembic revision --autogenerate -m "desc"       # generate new
alembic downgrade -1                            # rollback one
```

If Supabase is unreachable locally, paste `migrations/manual_apply.sql` into the Supabase SQL editor (idempotent).
