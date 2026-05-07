# HastleFam — Get It Working Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get HastleFam bot fully operational on the VPS — all features wired, scheduler running, Redis enabled, production DB up to date.

**Architecture:** All major features (duplicate confirmation, /cashflow, /review, /recurring, debt reminders, gap check) are already coded and merged to main. The remaining work is: (1) wire the recurring_reminders job into APScheduler so it actually fires, (2) fix the broken local venv so tests can run, and (3) verify production deployment has Redis configured and migrations applied.

**Tech Stack:** Python 3.11, FastAPI, aiogram 3, APScheduler, SQLAlchemy, Alembic, Supabase Postgres, Redis (optional but needed for duplicate confirmation)

---

## Reality check — what's already done

| Feature | Status | Where |
|---|---|---|
| Duplicate confirmation dialog | ✅ Built + wired | `capture.py` + `duplicate_handler.py` |
| /cashflow 60-day projection | ✅ Built + wired | `cashflow.py` + `finance_service.py` |
| /review weekly summary | ✅ Built + wired | `review.py` |
| /recurring add/delete/list | ✅ Built + wired | `recurring.py` |
| Planned income in projections | ✅ Built | `finance_service.upcoming_transactions` includes INCOME direction |
| PlannedPayment consolidation | ✅ Done | Both digest + /upcoming use `Transaction(is_planned=True)` |
| Debt due-date reminders | ✅ Built | `recurring_reminders.py` |
| Gap check on past months | ✅ Built + wired | `month.py` lines 317–701 |
| Corrections page → primary_tag | ✅ Fixed | `finance.py` POST writes `primary_tag` |

**What's NOT done:**
1. `recurring_reminders.run_recurring_reminders()` is never called — no scheduler, no API route
2. Local `.venv` is broken (hardcoded path to old location `/Users/Max/Desktop/hastlefam`)
3. Production: Redis URL may be `localhost` (duplicate confirmation silently drops without it)
4. Production: migrations 0001–0020 may not all be applied to Supabase DB

---

## Task 1: Wire recurring_reminders into APScheduler

**Files:**
- Modify: `app/application/jobs/daily_status_job.py`

The `run_recurring_reminders()` function in `recurring_reminders.py` creates planned transactions from `RecurringPayment` rows and sends debt due-date reminders. It is synchronous (uses `asyncio.run` internally) so it must run in a thread executor inside the async scheduler.

- [ ] **Step 1: Read daily_status_job.py start function to find the insert point**

Open `app/application/jobs/daily_status_job.py`, locate `start_daily_status_scheduler()`.

- [ ] **Step 2: Add recurring_reminders job to the scheduler**

In `app/application/jobs/daily_status_job.py`, modify `start_daily_status_scheduler()`:

```python
def start_daily_status_scheduler(bot) -> AsyncIOScheduler:
    """Create and start the APScheduler for daily status. Returns scheduler instance."""
    scheduler = AsyncIOScheduler(timezone=MSK)
    scheduler.add_job(
        send_daily_status,
        trigger="cron",
        hour=10,
        minute=0,
        kwargs={"bot": bot},
        id="daily_status",
        replace_existing=True,
    )
    # Run recurring reminders daily at 09:00 MSK (before digest so planned txs appear in digest)
    scheduler.add_job(
        _run_recurring_reminders_job,
        trigger="cron",
        hour=9,
        minute=0,
        id="recurring_reminders",
        replace_existing=True,
    )
    scheduler.start()
    log.info("daily_status scheduler started (10:00 MSK)")
    log.info("recurring_reminders scheduler started (09:00 MSK)")
    return scheduler
```

Add the wrapper function above `start_daily_status_scheduler`:

```python
async def _run_recurring_reminders_job() -> None:
    """Async wrapper: run synchronous recurring_reminders in thread pool."""
    import asyncio
    from app.application.jobs.recurring_reminders import run_recurring_reminders
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, run_recurring_reminders)
        log.info("recurring_reminders completed: %s", result)
    except Exception as exc:
        log.error("recurring_reminders failed: %s", exc, exc_info=True)
```

- [ ] **Step 3: Verify import — no circular import**

Run: `python3 -c "from app.application.jobs.daily_status_job import start_daily_status_scheduler; print('ok')"` from the project root (with a working venv — see Task 2 first if venv is broken).

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add app/application/jobs/daily_status_job.py
git commit -m "feat: schedule recurring_reminders at 09:00 MSK daily

Wires run_recurring_reminders() into APScheduler so recurring payments
auto-create planned transactions and debt due-date reminders fire.
Runs at 09:00 MSK, one hour before the daily digest."
```

---

## Task 2: Fix local venv so tests run

**Files:**
- No code changes — environment setup only

The `.venv` hardcodes `/Users/Max/Desktop/hastlefam/` (old path). The project moved to `/Users/Max/Desktop/claude/hastlefam/`. The venv must be recreated.

- [ ] **Step 1: Remove broken venv**

```bash
rm -rf .venv
```

- [ ] **Step 2: Create fresh venv with Python 3.11**

```bash
python3.11 -m venv .venv
```

If Python 3.11 is not at `python3.11`, find it: `ls /usr/local/bin/python*` or `brew list | grep python`.

If 3.11 is not installed: `brew install python@3.11` then `python3.11 -m venv .venv`.

- [ ] **Step 3: Install dependencies**

```bash
.venv/bin/pip install -e ".[test]"
```

- [ ] **Step 4: Run test suite**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: all tests pass. If failures exist, note them — do not commit fixes without reviewing the failure first.

- [ ] **Step 5: Add venv to .gitignore if not already**

```bash
grep -q "^\.venv" .gitignore || echo ".venv" >> .gitignore
```

---

## Task 3: Production checklist — Redis on VPS

**Files:**
- Modify: `.env` (VPS copy only — never commit secrets)
- Check: `/etc/systemd/system/hastlefam-*.service` or however the VPS runs the bot

**The problem:** `REDIS_URL=redis://localhost:6379/0` in `.env`. On VPS this works if Redis is installed and running locally. Confirm this is the case.

- [ ] **Step 1: SSH to VPS, check Redis is running**

```bash
systemctl status redis || redis-cli ping
```

Expected: `PONG`. If Redis is not installed: `apt install redis-server && systemctl enable redis && systemctl start redis`.

- [ ] **Step 2: Confirm REDIS_URL in production .env**

Check the VPS `.env` (or environment variables set in the service file):

```bash
grep REDIS_URL /path/to/hastlefam/.env
```

Must be `redis://localhost:6379/0` (or the correct Redis host if remote).

- [ ] **Step 3: Verify duplicate confirmation works with Redis**

With the bot running, send the same transaction twice in Telegram (e.g., `100 кофе`).

Expected first send: `✅ Записал.`
Expected second send within 5 minutes: `⚠️ Похоже на повтор. Похожая запись уже была недавно. Записать ещё раз?` with ✅ Да | ❌ Нет buttons.

If you still see `Похоже на дубль, пропустил.` silently — Redis is not connected. Fix the REDIS_URL.

---

## Task 4: Production checklist — apply migrations

**Files:**
- No code changes — DB operations only

Migrations 0001–0020 must all be applied to the Supabase production DB. The `DATABASE_URL` in `.env` points to Supabase.

- [ ] **Step 1: Check current migration state against production**

From the project root (with working venv):

```bash
ALEMBIC_DATABASE_URL="postgresql+psycopg2://postgres.sfzyqdpckgyznuhunygj:...@aws-1-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require" \
.venv/bin/alembic current
```

Expected: `0020_add_is_internal_transfer (head)` — confirms all 20 migrations applied.

If it shows an older revision, or shows an error about the alembic_version table missing, proceed to Step 2.

- [ ] **Step 2: Apply all pending migrations**

```bash
.venv/bin/alembic upgrade head
```

Expected output: applies all pending migrations, ends with `Running upgrade ... -> 0020_add_is_internal_transfer`.

If the `hastlefam` schema doesn't exist, the first migration creates it.

If Alembic fails due to existing tables (fresh Supabase project with manual SQL applied): run `migrations/manual_apply.sql` in the Supabase SQL editor, then stamp: `.venv/bin/alembic stamp head`.

- [ ] **Step 3: Verify core tables exist**

In Supabase SQL editor:
```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'hastlefam'
ORDER BY table_name;
```

Expected tables include: `accounts`, `balance_snapshots`, `category_budgets`, `debts`, `event_log`, `finance_categories`, `fx_rates`, `households`, `merchant_tag_rules`, `planned_payments`, `recurring_payments`, `tag_budgets`, `transactions`, `users`.

---

## Task 5: Seed production DB (if first-time setup)

**Files:**
- No code changes — seed script only

If the production DB is empty (no households, users, or categories), run the seed scripts.

- [ ] **Step 1: Check if household exists**

In Supabase SQL editor:
```sql
SELECT id, name FROM hastlefam.households LIMIT 5;
```

If rows exist — skip this task.

- [ ] **Step 2: Run seed scripts against production**

```bash
DATABASE_URL="postgresql+psycopg2://..." .venv/bin/python -m app.seeds.run_all
```

This creates the default household, users, categories, and accounts. Check the seed scripts in `app/seeds/` first to understand what they create.

- [ ] **Step 3: Link your Telegram user to the DB user**

In Supabase SQL editor (replace with your actual Telegram ID and household UUID):
```sql
UPDATE hastlefam.users
SET telegram_id = '123456789'
WHERE name = 'Max';
```

Verify with `/start` in Telegram — bot should respond without "не вижу твой профиль".

---

## Task 6: Smoke test all commands on production

No code changes — end-to-end verification.

- [ ] **Step 1: Basic capture**

Send `100 кофе` → expect `✅ Записал. 100 ₽ · кофе`

- [ ] **Step 2: Planned expense**

Send `3000 аренда 25-05` → expect capture with future date. Then `/upcoming` → expect it appears.

- [ ] **Step 3: Planned income**

Send `+80000 зарплата 25-05` → Then `/cashflow` → expect income line shows `💰 +80 000 ₽`.

- [ ] **Step 4: Cashflow**

`/cashflow` → expect balances, income/expense lines, projection at 30 and 60 days.

- [ ] **Step 5: Review**

`/review` → expect one message with balances, MTD spend/income, planned items, projection, risk flags.

- [ ] **Step 6: Recurring**

`/recurring add Netflix 49.90 USD 15` → `/recurring` → expect Netflix in list.

- [ ] **Step 7: Duplicate confirmation**

Send same transaction twice within 5 minutes → second should prompt ⚠️ confirmation. Tap ✅ Да → both saved. Tap ❌ Нет → second dropped.

- [ ] **Step 8: Debt reminder**

Create a debt with a near due date:
```
дал 500 Тесту
```
Then manually set `due_date` in Supabase to today or tomorrow:
```sql
UPDATE hastlefam.debts SET due_date = CURRENT_DATE + 1 WHERE counterparty_name = 'Тест';
```
Wait for 09:00 MSK or trigger `run_recurring_reminders()` manually — expect Telegram reminder.

- [ ] **Step 9: Gap check**

`/month` → navigate to a past month → tap `✅ Проверить` → expect gap report showing zero-transaction day runs and untagged count.

---

## Self-review

**Spec coverage:**
- Wire recurring_reminders → Task 1 ✅
- Fix venv → Task 2 ✅
- Redis on VPS → Task 3 ✅
- Migrations → Task 4 ✅
- Seed DB → Task 5 ✅
- End-to-end smoke test → Task 6 ✅

**No placeholders:** all steps show exact commands, exact SQL, exact expected outputs.

**Type consistency:** no new types or method signatures introduced — all references to existing methods (`run_recurring_reminders`, `start_daily_status_scheduler`, `upcoming_transactions`) match their current signatures.
