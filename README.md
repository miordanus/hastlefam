# HastleFam Money MVP

Product behavior is defined in:

docs/hastlefam_product_contract.md

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

## OpenClaw — mass add transactions

CLI tool for bulk-adding transactions from voice transcriptions or text dumps.

### Setup

Set env vars (in addition to the existing `DATABASE_URL` etc.):

```bash
export SUPABASE_URL=https://<ref>.supabase.co
export SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
export HASTLEFAM_HOUSEHOLD_ID=ed36b994-81e3-4fa0-b860-205381ba4681
```

### Usage

```bash
# Single-line or slash-separated
python3 -m openclaw.mass_add "12.03 350 продукты / 14.03 +90000 зп"

# Multiline via stdin
cat transactions.txt | python3 -m openclaw.mass_add

# Skip confirmation prompt (for agent/script use)
python3 -m openclaw.mass_add "350 кафе" --confirm

# Machine-readable JSON output
python3 -m openclaw.mass_add "350 кафе" --confirm --json

# Include duplicate-fingerprint rows (normally skipped)
python3 -m openclaw.mass_add "350 кафе" --confirm --force-duplicates
```

### Input format

One transaction per line (or separated by ` / `). Each line:
- Optional date: `DD.MM`, `DD-MM`, `DD/MM`, `YYYY-MM-DD`, `вчера`, `позавчера` (defaults to today)
- Amount: bare number or `+N` (+ marks income)
- Optional currency: `USD`, `EUR`, `AMD`, `USDT` (defaults to `RUB`)
- Income keywords: `зп`, `зарплата`, `доход`, `salary`, `income`
- Transfer keyword: `перевод`, `transfer` → sets `is_internal_transfer=true`
- Remainder: merchant description
- `[planned]` suffix → marks as planned (not actual spend)

Rows that can't be parsed get `parse_status=needs_correction` and are shown in the preview but still inserted — never silently dropped.
