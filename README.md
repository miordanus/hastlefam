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
