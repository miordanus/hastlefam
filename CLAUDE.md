# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Telegram-first money copilot for a two-person household. FastAPI backend + aiogram 3 Telegram bot, deployed on Railway (two separate services), database on Supabase (PostgreSQL, schema `hastlefam`).

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

Tests use SQLite in-memory (no real DB needed). `conftest.py` sets dummy env vars before any app import so `Settings()` doesn't crash.

---

## Architecture

### Two processes, one codebase

**Web** (`app/main.py`) — FastAPI + Jinja2 dashboard. No bot logic, `TELEGRAM_BOT_TOKEN` not required.  
**Worker** (`app/bot/main.py`) — aiogram 3 polling bot + APScheduler. No HTTP port.  
Railway `Procfile` maps `web:` → uvicorn, `worker:` → bot. `railway.json` has no `startCommand` and no healthcheck entry.

### Request flow: Telegram message → DB

1. `bot/main.py` polls Telegram; `LoggingMiddleware` runs first, then `IdempotencyMiddleware` (Redis dedup by `chat_id+message_id`).
2. Routers are registered in priority order: `cancel` → command handlers → `exchange_router` → `inline_actions_router` → `duplicate_router` → ... → `capture_router` (catch-all last).
3. `capture.py` dispatches to: `debt_parser` → `split_parser` → `expense_parser` (in that order; first match wins).
4. After parsing, `autocat_service.lookup_tag()` applies merchant→tag rules; `finance_service` or direct DB write saves the `Transaction`.
5. Post-capture inline keyboard (date / tag / currency correction) is built by `inline_actions.build_post_capture_keyboard()`.

### Database layer

All ORM models in `app/infrastructure/db/models/all_models.py`. All tables live in the `hastlefam` Postgres schema (set via `connect_args={'options': '-csearch_path=hastlefam'}` in `session.py`).

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

`fx_service.py` fetches daily rates from CBR XML feed (no API key). Rates stored as `1 foreign_currency = X RUB`. `convert_to_rub()` falls back up to 7 days if today's rate is missing. Currencies tracked: USD, EUR, PLN, USDT (proxied as USD), AMD.

### Auto-categorization rules

`autocat_service.py` — per-household `merchant_tag_rules` table. Auto-learned after 3 identical merchant+tag combinations. `/rules` command manages rules manually. Merchant matching is case-insensitive, full-string (not substring).

### Redis (optional)

Bot starts without Redis. When available: distributed polling lock (`hastlefam:bot:poller`, TTL 60s, renewed every 20s) prevents two instances polling simultaneously. On `TelegramConflictError`, lock is released before `os._exit(1)`. New instance waits up to 70s for stale lock to expire.

### Observability

- Structured JSON logs via `structlog` (`app/infrastructure/logging/logger.py`).
- `event_log` DB table for domain events via `observability/event_logger.py`.
- `observability/prompt_logger.py` for LLM prompt/response logging.

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
