# Planned Payment Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Transaction(is_planned=True)` the single bot-visible planned-payment source of truth, add `[план]` text capture, and fix the reminders job to read from it with Russian text.

**Architecture:** Four surgical changes to existing files — no new abstractions, no new tables, no LLM involvement. Parser gains one regex token; capture handler passes the flag through; reminders job replaces a `PlannedPayment` query with a direct `Transaction` query; English reminder string becomes Russian.

**Tech Stack:** Python 3.11, aiogram 3, SQLAlchemy, pytest + SQLite in-memory, structlog.

---

## Files Changed

| File | What changes |
|---|---|
| `app/bot/parsers/expense_parser.py` | Add `is_planned: bool = False` to `ParseResult`; strip `[план]`/`[plan]` token in `parse()` |
| `app/bot/handlers/capture.py` | Pass `result.is_planned` to `Transaction(is_planned=...)`; adjust confirmation message and keyboard |
| `app/application/jobs/recurring_reminders.py` | Replace `upcoming_payments()` (reads `PlannedPayment`) with direct `Transaction(is_planned=True)` query; Russian text; update `EventLog` entity_type; move `TransactionDirection` import to top level |
| `tests/test_capture.py` | Add `[план]` parser tests |
| `tests/test_recurring_reminders.py` | New file — test reminder dedup and transaction query filtering |

---

## Task 1: Add `is_planned` field and `[план]` token to expense_parser

**Files:**
- Modify: `app/bot/parsers/expense_parser.py`
- Modify: `tests/test_capture.py`

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_capture.py`:

```python
# ─── Planned flag [план] ──────────────────────────────────────────────────────

def test_plan_token_sets_is_planned():
    r = parse("15.06 5000 аренда [план]")
    assert r.ok
    assert r.is_planned is True
    assert r.merchant == "аренда"
    assert r.amount == Decimal("5000")


def test_plan_token_english():
    r = parse("5000 netflix [plan]")
    assert r.ok
    assert r.is_planned is True
    assert r.merchant == "netflix"


def test_no_plan_token_is_false():
    r = parse("5000 продукты")
    assert r.is_planned is False


def test_plan_token_with_tag():
    r = parse("5000 аренда #жильё [план]")
    assert r.is_planned is True
    assert r.primary_tag == "жильё"
    assert r.merchant == "аренда"


def test_plan_token_income():
    r = parse("+50000 зп [план]")
    assert r.ok
    assert r.is_planned is True
    assert r.direction == TransactionDirection.INCOME
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_capture.py::test_plan_token_sets_is_planned -v
```

Expected: `AttributeError: 'ParseResult' object has no attribute 'is_planned'`

- [ ] **Step 3: Add `_PLANNED_RE` and `is_planned` field**

In `app/bot/parsers/expense_parser.py`:

After line 65 (`_INCOME_RE = re.compile(r"^\+")`), add:

```python
# Planned-payment marker: [план] or [plan] (case-insensitive, any position)
_PLANNED_RE = re.compile(r"\[план\]|\[plan\]", re.IGNORECASE)
```

In the `ParseResult` dataclass (after line 90 `error: Optional[str] = None`), add:

```python
    is_planned: bool = False
```

In `parse()` at line 102 (right after `text = text.strip()`), add:

```python
    is_planned = bool(_PLANNED_RE.search(text))
    text = _PLANNED_RE.sub("", text).strip()
```

At the final `return ParseResult(...)` call (line 177), add `is_planned=is_planned` to the constructor:

```python
    return ParseResult(
        direction=direction,
        amount=amount,
        currency=currency,
        currency_explicit=currency_explicit,
        merchant=merchant_str,
        primary_tag=primary_tag,
        extra_tags=extra_tags,
        occurred_date=occurred_date,
        date_explicit=date_explicit,
        is_planned=is_planned,
    )
```

- [ ] **Step 4: Run all parser tests**

```
pytest tests/test_capture.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/bot/parsers/expense_parser.py tests/test_capture.py
git commit -m "feat(parser): add [план]/[plan] token → ParseResult.is_planned"
```

---

## Task 2: Pass `is_planned` through the capture handler

**Files:**
- Modify: `app/bot/handlers/capture.py`

- [ ] **Step 1: Change Transaction construction at line 176**

In `app/bot/handlers/capture.py`, find the `Transaction(...)` block. Change line 176:

```python
                is_planned=False,  # ЗАКОН: capture = actual
```

to:

```python
                is_planned=result.is_planned,
```

- [ ] **Step 2: Suppress "📅 В план" button when already planned**

Find the `build_post_capture_keyboard(...)` call near line 206. Change:

```python
    keyboard = build_post_capture_keyboard(
        tx_id=tx_id,
        tag_missing=effective_tag is None,
        date_explicit=result.date_explicit,
        currency_explicit=result.currency_explicit,
        date_is_future=result.occurred_date > today,
    )
```

to:

```python
    keyboard = build_post_capture_keyboard(
        tx_id=tx_id,
        tag_missing=effective_tag is None,
        date_explicit=result.date_explicit,
        currency_explicit=result.currency_explicit,
        date_is_future=result.occurred_date > today and not result.is_planned,
    )
```

- [ ] **Step 3: Add planned confirmation message branch**

Find the message construction block near lines 217–222:

```python
    if effective_tag:
        auto_hint = " 🤖" if autocat_applied else ""
        body = f"✅ Записал{direction_label}.\n{result.amount} {result.currency.value} · {result.merchant} · #{effective_tag}{auto_hint}"
    else:
        body = f"✅ Записал{direction_label}.\n{result.amount} {result.currency.value} · {result.merchant}"
```

Replace with:

```python
    if result.is_planned:
        due_str = result.occurred_date.strftime("%d.%m")
        tag_part = f" · #{effective_tag}" if effective_tag else ""
        body = f"📅 Запланировал{direction_label}.\n{result.amount} {result.currency.value} · {result.merchant}{tag_part} (до {due_str})"
    elif effective_tag:
        auto_hint = " 🤖" if autocat_applied else ""
        body = f"✅ Записал{direction_label}.\n{result.amount} {result.currency.value} · {result.merchant} · #{effective_tag}{auto_hint}"
    else:
        body = f"✅ Записал{direction_label}.\n{result.amount} {result.currency.value} · {result.merchant}"
```

- [ ] **Step 4: Run existing tests to check nothing broke**

```
pytest tests/ -v --ignore=tests/openclaw -q
```

Expected: all pass (capture tests are parser-level; handler tests require bot mocking which isn't in the suite).

- [ ] **Step 5: Commit**

```bash
git add app/bot/handlers/capture.py
git commit -m "feat(capture): use result.is_planned from parser; planned confirmation message"
```

---

## Task 3: Fix recurring_reminders to read from Transaction + Russian text

**Files:**
- Modify: `app/application/jobs/recurring_reminders.py`

- [ ] **Step 1: Move `TransactionDirection` import to top of file**

At the top of `app/application/jobs/recurring_reminders.py`, the current import is:

```python
from app.infrastructure.db.models import Debt, EventLog, RecurringPayment, Transaction, User
```

Add `TransactionDirection` to the top-level imports block:

```python
from app.domain.enums import TransactionDirection
```

- [ ] **Step 2: Replace the `upcoming_payments` block with a direct Transaction query**

Find lines 32–58 (the `upcoming` block inside the `for household_id` loop):

```python
                upcoming = FinanceService(db).upcoming_payments(str(household_id), days)
                for item in upcoming:
                    recurring_id = uuid.UUID(item["id"])
                    if _already_sent(db, household_id, recurring_id):
                        skipped += 1
                        continue
                    text = f"Reminder: {item['title']} due {item['due_date']} ({item['amount']} {item['currency']})"
                    users = db.query(User).filter(User.household_id == household_id, User.is_active.is_(True)).all()
                    for user in users:
                        try:
                            asyncio.run(_send(bot, int(user.telegram_id), text))
                        except Exception as exc:
                            logger.warning('reminder.send_failed', user_id=str(user.id), error=str(exc))
                            continue
                    db.add(
                        EventLog(
                            household_id=household_id,
                            user_id=None,
                            event_type="recurring_reminder_sent",
                            entity_type="recurring_payment",
                            entity_id=recurring_id,
                            payload={"due_date": item["due_date"], "days": days},
                            severity="info",
                        )
                    )
                    sent += 1
```

Replace with:

```python
                today = datetime.now(timezone.utc).date()
                soon = today + timedelta(days=days)
                today_dt = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
                until_dt = datetime(soon.year, soon.month, soon.day, 23, 59, 59, tzinfo=timezone.utc)

                planned_txs = db.query(Transaction).filter(
                    Transaction.household_id == household_id,
                    Transaction.is_planned.is_(True),
                    Transaction.is_skipped.is_(False),
                    Transaction.occurred_at >= today_dt,
                    Transaction.occurred_at <= until_dt,
                    Transaction.direction != TransactionDirection.TRANSFER,
                    Transaction.direction != TransactionDirection.EXCHANGE,
                ).order_by(Transaction.occurred_at.asc()).all()

                for tx in planned_txs:
                    if _already_sent(db, household_id, tx.id):
                        skipped += 1
                        continue
                    due_str = tx.occurred_at.strftime("%d.%m")
                    amount_int = int(tx.amount) if tx.amount == int(tx.amount) else tx.amount
                    currency_str = tx.currency.value if tx.currency else "RUB"
                    reminder_text = f"📅 Платёж: {tx.merchant_raw} — {amount_int} {currency_str} ({due_str})"
                    users = db.query(User).filter(
                        User.household_id == household_id, User.is_active.is_(True)
                    ).all()
                    for user in users:
                        try:
                            asyncio.run(_send(bot, int(user.telegram_id), reminder_text))
                        except Exception as exc:
                            logger.warning("reminder.send_failed", user_id=str(user.id), error=str(exc))
                            continue
                    db.add(
                        EventLog(
                            household_id=household_id,
                            user_id=None,
                            event_type="recurring_reminder_sent",
                            entity_type="planned_transaction",
                            entity_id=tx.id,
                            payload={"due_date": tx.occurred_at.date().isoformat(), "days": days},
                            severity="info",
                        )
                    )
                    sent += 1
```

- [ ] **Step 3: Update `_already_sent()` to match new entity_type**

Find `_already_sent()` at line 158. Change:

```python
            EventLog.event_type == "recurring_reminder_sent",
            EventLog.entity_id == recurring_id,
```

(the full function, unchanged except one field):

```python
def _already_sent(db: Session, household_id: uuid.UUID, tx_id: uuid.UUID) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=20)
    hit = (
        db.query(EventLog)
        .filter(
            EventLog.household_id == household_id,
            EventLog.event_type == "recurring_reminder_sent",
            EventLog.entity_type == "planned_transaction",
            EventLog.entity_id == tx_id,
            EventLog.created_at >= cutoff,
        )
        .first()
    )
    return bool(hit)
```

(The parameter was renamed from `recurring_id` to `tx_id` for clarity — update the signature line.)

- [ ] **Step 4: Remove the now-shadowed `today` variable in the debt block**

The original code redeclared `today` at line 60 inside the debt block:
```python
                today = datetime.now(timezone.utc).date()
                soon = today + timedelta(days=days)
```

Since `today` and `soon` are now declared at the top of the household loop (in the planned_txs block), remove the duplicates in the debt section. The debt section (lines 59–97) should reference the `today` and `soon` already set.

Find in the debt block:
```python
                # ── Debt due-date reminders ─────────────────────────────
                today = datetime.now(timezone.utc).date()
                soon = today + timedelta(days=days)
```

Remove those two lines (they shadow the variables set at the top of the loop).

- [ ] **Step 5: Run tests**

```
pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/application/jobs/recurring_reminders.py
git commit -m "fix(reminders): read from Transaction(is_planned=True); Russian text; fix entity_type"
```

---

## Task 4: Tests for reminder dedup logic

**Files:**
- Create: `tests/test_recurring_reminders.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for recurring_reminders — dedup and transaction query logic."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.infrastructure.db.models import EventLog, Transaction
from app.domain.enums import Currency, TransactionDirection
from app.application.jobs.recurring_reminders import _already_sent
from tests.conftest import HOUSEHOLD_ID, ACCOUNT_ID, USER_ID


def _make_planned_tx(db, household_id, occurred_at, merchant="аренда", amount=5000):
    tx = Transaction(
        id=uuid.uuid4(),
        household_id=household_id,
        direction=TransactionDirection.EXPENSE,
        amount=amount,
        currency=Currency.RUB,
        occurred_at=occurred_at,
        merchant_raw=merchant,
        source="telegram",
        parse_status="ok",
        is_planned=True,
        extra_tags=[],
    )
    db.add(tx)
    db.flush()
    return tx


def test_already_sent_returns_false_with_no_log(seeded_db):
    tx = _make_planned_tx(
        seeded_db,
        HOUSEHOLD_ID,
        datetime.now(timezone.utc) + timedelta(days=2),
    )
    seeded_db.commit()
    assert _already_sent(seeded_db, HOUSEHOLD_ID, tx.id) is False


def test_already_sent_returns_true_after_log_written(seeded_db):
    tx = _make_planned_tx(
        seeded_db,
        HOUSEHOLD_ID,
        datetime.now(timezone.utc) + timedelta(days=2),
    )
    seeded_db.add(
        EventLog(
            household_id=HOUSEHOLD_ID,
            user_id=None,
            event_type="recurring_reminder_sent",
            entity_type="planned_transaction",
            entity_id=tx.id,
            payload={},
            severity="info",
        )
    )
    seeded_db.commit()
    assert _already_sent(seeded_db, HOUSEHOLD_ID, tx.id) is True


def test_already_sent_ignores_stale_log(seeded_db):
    tx = _make_planned_tx(
        seeded_db,
        HOUSEHOLD_ID,
        datetime.now(timezone.utc) + timedelta(days=2),
    )
    stale_time = datetime.now(timezone.utc) - timedelta(hours=25)
    log = EventLog(
        household_id=HOUSEHOLD_ID,
        user_id=None,
        event_type="recurring_reminder_sent",
        entity_type="planned_transaction",
        entity_id=tx.id,
        payload={},
        severity="info",
    )
    seeded_db.add(log)
    seeded_db.flush()
    # Backdate the created_at
    seeded_db.execute(
        __import__("sqlalchemy").text(
            "UPDATE event_log SET created_at = :t WHERE id = :id"
        ),
        {"t": stale_time.isoformat(), "id": str(log.id)},
    )
    seeded_db.commit()
    assert _already_sent(seeded_db, HOUSEHOLD_ID, tx.id) is False
```

- [ ] **Step 2: Run tests**

```
pytest tests/test_recurring_reminders.py -v
```

Expected: all 3 pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_recurring_reminders.py
git commit -m "test(reminders): add dedup logic tests for planned_transaction entity_type"
```

---

## Task 5: Fix duplicate detection fallback message

**Files:**
- Modify: `app/bot/handlers/capture.py`

**Context:** `duplicate_handler.py` is already imported and registered in `bot/main.py` (lines 17, 172). The confirmation dialog works correctly when Redis is available. The only remaining gap is when Redis is unavailable — `draft_store.store()` returns `None` and the code currently says `"Похоже на дубль, пропустил."` with no recourse for the user.

- [ ] **Step 1: Replace the silent-drop fallback message**

In `app/bot/handlers/capture.py`, find line 144:

```python
                else:
                    await message.answer("Похоже на дубль, пропустил.")
```

Replace with:

```python
                else:
                    await message.answer(
                        "⚠️ Похоже на повтор — такая запись уже была сегодня.\n"
                        "Если это другая трата, отправь снова."
                    )
```

- [ ] **Step 2: Run tests**

```
pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add app/bot/handlers/capture.py
git commit -m "fix(capture): replace silent duplicate drop with informative fallback message"
```

---

## Verification Checklist

After all tasks, run the full suite and manually verify:

- [ ] `pytest tests/ -q` — all green
- [ ] `parse("15.06 5000 аренда [план]")` → `is_planned=True`, `merchant="аренда"`, `occurred_date=date(current_year, 6, 15)`
- [ ] `parse("5000 кофе")` → `is_planned=False`
- [ ] `parse("5000 кофе [plan]")` → `is_planned=True`
- [ ] `capture.py` Transaction block: `is_planned=result.is_planned` (not hardcoded `False`)
- [ ] Planned capture confirmation message starts with `📅 Запланировал` not `✅ Записал`
- [ ] "📅 В план" button does NOT appear in keyboard when `result.is_planned=True`
- [ ] `recurring_reminders.py` reminder loop: no reference to `PlannedPayment` or `upcoming_payments()`
- [ ] Reminder text format: `📅 Платёж: аренда — 5000 RUB (15.06)` (Russian, no "Reminder:")
- [ ] `EventLog.entity_type` written as `"planned_transaction"` not `"recurring_payment"`
- [ ] `_already_sent()` signature is `(db, household_id, tx_id)` and filters `entity_type="planned_transaction"`
- [ ] `today` and `soon` not declared twice in the reminder loop (debt block should reuse the same vars)
- [ ] Duplicate fallback message (Redis unavailable path): `"⚠️ Похоже на повтор..."` not `"Похоже на дубль, пропустил."`
- [ ] `duplicate_handler` router already registered in `bot/main.py` — no change needed there
- [ ] `git diff --stat` — only 5 files changed, no new tables, no new routes
