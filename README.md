# HastleFam MVP

Telegram-first family operating system for a 2-person household focused on finances and sprint execution.

## Features in this MVP
- FastAPI backend + lightweight dashboard pages
- aiogram Telegram bot capture/review skeleton
- SQLAlchemy models for required entities
- Alembic migrations + seed migration/data scripts
- LLM abstraction with strict prompt/output contracts
- JSON schema + Pydantic validation for LLM drafts
- Event logging, prompt logging, structured logs

## Shared Supabase schema isolation (required)
This project uses a dedicated PostgreSQL schema: `hastlefam`.
All app tables are created in `hastlefam` (not `public`).

### 1) First SQL command to run
Run this once on the target database before the first migration (safe if repeated):

```sql
CREATE SCHEMA IF NOT EXISTS hastlefam;
```

### 2) How to use `DATABASE_URL` and `ALEMBIC_DATABASE_URL`
- `DATABASE_URL`: runtime DB connection used by the FastAPI app, bot, and seed scripts.
- `ALEMBIC_DATABASE_URL`: migration DB connection used by Alembic.
- Both should point to the same database in normal local/dev setup.
- Do **not** set them to a `public`-specific search path; Sprint 0 is hard-wired to use schema `hastlefam`.

### 3) How to verify tables are in `hastlefam` (not `public`)
After `alembic upgrade head`, run:

```sql
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_name IN ('households','users','tasks','transactions','event_log')
ORDER BY table_name, table_schema;
```

Expected: each listed table appears with `table_schema = 'hastlefam'`.

### 4) Legacy `public` -> `hastlefam` migration note
If older deployments created HastleFam tables in `public`, run the latest Alembic head to apply the legacy move migration.

That revision:
- ensures `hastlefam` exists, and
- moves only these tables from `public` to `hastlefam` when `public.<table>` exists and `hastlefam.<table>` does not:
  `households`, `users`, `areas`, `sprints`, `tasks`, `decisions`, `notes`, `meetings`, `transactions`, `finance_categories`, `accounts`, `recurring_payments`, `savings_goals`, `reminders`, `digests`, `llm_drafts`, `event_log`.

It is idempotent (`to_regclass(...)` checks) and does not touch `auth.users`.

## Quick start
1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -e .`
3. `cp .env.example .env`
4. Configure Postgres/Supabase and env vars.
5. `alembic upgrade head`
6. `python -m app.seeds.run_all`
7. API: `uvicorn app.main:app --reload`
8. Bot: `python -m app.bot.main`

## Notes
- LLM never writes business tables directly; only writes `llm_drafts`.
- Every task requires `owner_user_id`.
- No role system/privacy separation in MVP.
