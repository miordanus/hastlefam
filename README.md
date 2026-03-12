# HastleFam Money MVP

Telegram-first money copilot for two (mine / wife / shared), optimized for quick daily capture and monthly money review.

## In scope (active MVP)
- Transactions, categories, accounts, recurring payments, owners.
- SQL-only import pipeline with raw layer + normalization.
- Telegram default expense capture from plain text (`149 biedronka`).
- Telegram commands: `/month` (calendar MTD), `/upcoming` (next 7 days).
- Web correction screen for uncategorized transactions and recurring linking.
- Daily recurring reminders with anti-duplicate control.

## Out of scope (frozen)
- Tasks/sprints/meetings/decisions flows.
- Goals/forecasting/investment advice.
- Bank integrations and non-SQL import sources.
- Rich dashboards and complex permissions.
- LLM-driven core finance logic.

## Quick start
1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -e .`
3. Configure `.env` (`DATABASE_URL`, `ALEMBIC_DATABASE_URL`, `TELEGRAM_BOT_TOKEN`...)
4. `alembic upgrade head`
5. `python -m app.seeds.run_all`
6. API: `uvicorn app.main:app --reload`
7. Bot: `python -m app.bot.main`

## Import flow
1. `POST /finance/import/sql` with SQL query payload.
2. Each row is first stored in `raw_import_transactions`.
3. Normalization creates `transactions` with safe autofill rules.
4. Low-confidence/incomplete rows are saved with `parse_status=needs_correction` and nullable category/account.
5. Dedup is enforced via `dedup_fingerprint`.

## Reminder job
Run recurring reminders manually (or from scheduler):

```python
from app.application.jobs.recurring_reminders import run_recurring_reminders
run_recurring_reminders(days=3)
```

## Known limitations
- Currency defaults to USD when not recognized.
- Owner/account autofill requires explicit source mapping in import payload.
- Reminder job currently assumes users have valid Telegram IDs in `users`.
- Legacy non-money modules remain in repo but are frozen for this MVP.
