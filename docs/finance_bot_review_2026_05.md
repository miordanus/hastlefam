# Finance Bot Review & Improvement Backlog
*Сессия: 2026-05-02*

> Advisor frame: optimize for a reliable workflow — capture → categorize → validate → review → decision.
> The highest-value outcome: know how much the month costs, what payments are coming, what debts exist, and what free balance you actually have.

---

## Part 1 — Current State Summary

### What the bot CAN do

**Capture**
- Free-text expense/income: `149 biedronka`, `+8000 зарплата`, `100 USD кофе`
- Debt capture: `дал 500 Васе` / `взял 1000 у Пети`
- Split across date range: `700 еда 13.03-19.03` (creates N per-day transactions)
- Currency exchange: `250 usdt → 230 eur` (with optional balance update)
- `/add` as alias for free-text

**Categorization**
- Auto-cat rules (merchant→tag, learned after 3 uses, managed via `/rules`)
- Post-capture inline correction: tag, date, currency
- `/inbox`: bulk review of untagged transactions

**Future payments**
- `/upcoming`: shows `Transaction(is_planned=True)` entries, mark-paid in-place
- Daily digest at 10:00 MSK: includes next-3-days planned payments

**Debts**
- Separate `Debt` table; capture via syntax; settle via `/debts` button

**Summaries**
- `/month`: spend + income + top tags + budget risks + untagged count + planned remaining; prev/next navigation; year view
- `/balances`: account snapshots, manual reconciliation, account history, net worth in RUB
- `/budgets`: per-tag monthly limits with rollover and 80%/100% alerts
- `/ask`: natural-language → SQL → OpenAI-formatted answer
- `Insights` button on `/month` (if `INSIGHTS_ENABLED=true`): 3-5 LLM bullet points

**Infrastructure**
- Redis distributed polling lock, idempotency middleware
- FX rates from CBR (daily, stored, 7-day fallback)
- `/finance/import/sql` endpoint for SQL-based import
- HTML corrections page (`/finance/corrections`)

---

### What the bot CANNOT do

- No 30–60 day cashflow view combining balances + incoming income + outgoing obligations
- No planned income — system only tracks planned expenses, making projections permanently pessimistic
- No previous-month recovery workflow — no guided gap-filling, no "what's missing in April?"
- No weekly review command — user must mentally combine `/month` + `/upcoming` + `/debts` + `/balances`
- No recurring payment management — `RecurringPayment` table is fully defined but entirely abandoned, no bot command touches it
- No debt due-date reminders — `Debt.due_date` field exists, no job fires on it
- Duplicate detection is a silent drop, not a confirmation
- `/upcoming` and morning digest show **different data** (two parallel planned payment systems)

---

## Part 2 — Main Gaps

Ordered by impact on the stated goal ("trusted 30–60 day financial map").

### Gap 1 — No cashflow view (biggest missing feature)
No single command answers: "given my balances, income, and obligations, how much free money do I have over the next 30–60 days?" This is the core decision-support feature that is absent.

### Gap 2 — Planned income is not tracked
`get_planned_total()` filters `direction=EXPENSE` only. A `+80000 зарплата 25-05` entry is excluded from all projections. The `/month` plan section shows only outgo. Mid-month the picture is always wrong.

### Gap 3 — Duplicate detection is a silent drop
Fingerprint match → "Похоже на дубль, пропустил." → nothing saved, no buttons, no recourse. `duplicate_handler.py` with a full confirmation dialog already exists but is never wired into the router in `bot/main.py`.

### Gap 4 — Two parallel planned payment systems
`PlannedPayment` (table, read by daily digest) and `Transaction(is_planned=True)` (read by `/upcoming`) are separate data sources. **Confirmed: they sometimes show different data.** All cashflow work depends on one clean source of truth.

### Gap 5 — No weekly review command
The mental overhead of combining 4–5 commands is exactly what the bot should eliminate.

### Gap 6 — RecurringPayment is a ghost
Fully modeled in the DB, zero bot commands create or read it. No way to say "Netflix, 49.90 USD, monthly on the 15th."

### Gap 7 — Debt due dates have no enforcement
`Debt.due_date` field exists. `recurring_reminders.py` ignores it entirely.

### Gap 8 — corrections page → primary_tag disconnect
The HTML `/finance/corrections` page sets `category_id`. Every bot summary uses `primary_tag`. Setting a category via the web page has zero effect on `/month`, `/budgets`, or `/ask`. Silent confusion trap.

---

## Part 3 — Improvement Backlog

---

### P0 — Must fix for trust

---

#### P0.1 — Duplicate detection: silent drop → confirmation dialog

**Problem:** SHA256 fingerprint match silently discards the transaction. Legitimate same-day repeat transactions (two coffees at the same café) are lost with no recourse.

**Why it matters:** Trust in "was it saved?" is broken. User may not notice for days.

**Current evidence:** `capture.py` — dedup fires, returns `"Похоже на дубль, пропустил."` with no buttons. `duplicate_handler.py` exists with a complete confirmation flow (router, `dup_yes`/`dup_no` callbacks, inline keyboard) but is never `include_router`-ed in `bot/main.py`.

**Proposed solution:** Wire `duplicate_handler.py` into `bot/main.py` (already written). In `capture.py`, route the fingerprint-match case to the duplicate handler instead of silent drop. Caveat: Telegram callback_data limit is 64 bytes — verify serialized draft fits or use Redis-keyed draft storage.

**Expected user outcome:** "The bot asked me to confirm. I confirmed, both transactions were saved. I didn't lose anything."

**Implementation complexity:** Low — the handler is already written.

**Risk:** Low.

**Dependencies:** None.

**Acceptance criteria:**
- Same-day same-amount same-merchant same-direction message shows "⚠️ Похоже на повтор" with ✅ Да | ❌ Нет
- ✅ saves and shows standard post-capture confirmation
- ❌ dismisses without saving
- A third identical send also prompts (fingerprint on confirmed duplicate is distinct)

---

#### P0.2 — Add planned income to upcoming and cashflow

**Problem:** `get_planned_total()` only tracks planned EXPENSE. A `+80000 зарплата 25-05` entry is excluded from all projections. The `/month` plan section always shows only outgo.

**Why it matters:** Stated mental model of free balance is `(balances) − (planned expenses) + (planned income)`. The bot currently computes only the middle term.

**Current evidence:** `finance_service.py::get_planned_total()` — only EXPENSE direction included. The data model fully supports `Transaction(is_planned=True, direction=INCOME)` — it's just never queried.

**Proposed solution:**
1. Add `planned_income_by_currency` to `get_planned_total()` return value.
2. Update `/month` to show a "📥 Ожидается: 80 000 ₽" line.
3. Future-dated `+` captures already work syntactically — just need display and query to use them.

**Expected user outcome:** "`+80000 зарплата 25-05` appears in `/upcoming` with a 💰 icon and offsets planned expenses in the month projection."

**Implementation complexity:** Low.

**Risk:** Low.

**Dependencies:** None.

**Acceptance criteria:**
- Future-dated income creates `Transaction(direction=INCOME, is_planned=True)`
- `/month` shows planned income line separately from planned expenses
- `/upcoming` shows planned income entries with distinct icon
- Projected balance uses: `current − planned_expenses + planned_income`

---

#### P0.3 — `/cashflow`: 30–60 day projection

**Problem:** No command answers "what is my projected free balance in 30 and 60 days?" All the data exists; nothing assembles it.

**Why it matters:** This is the stated primary goal. Without it the bot is a ledger, not a decision tool.

**Current evidence:** `Account + BalanceSnapshot` (current balance), `Transaction(is_planned=True)` (outgo/income), `Debt` (obligations). No command combines them.

**Proposed solution:** New `/cashflow` command:
```
💰 Кэшфлоу — следующие 60 дней

Текущие балансы: 42 500 ₽ | 800 $

Планируется получить:
• 25.05 · Зарплата · +80 000 ₽

Планируется потратить:
• 15.05 · Netflix · 49.90 $
• 20.05 · Аренда · 30 000 ₽

Долги к выплате:
• Петя · 3 000 ₽ (до 30.05)

Прогноз свободного остатка:
• Через 30 дней: ~89 000 ₽
• Через 60 дней: ~71 000 ₽
```

Pure arithmetic. No LLM. Projection model: `(account balances in RUB) − (planned expenses) + (planned income) − (debts with due dates in window)`.

**Expected user outcome:** "I run `/cashflow` before a large purchase and know whether I can afford it without keeping anything in my head."

**Implementation complexity:** Medium — new handler + new `finance_service` method. No new DB tables.

**Risk:** Low. Degrades gracefully if data is sparse.

**Dependencies:** P0.2 (planned income), P0.4 (one clean planned data source).

**Acceptance criteria:**
- `/cashflow` shows balances, planned income, planned expenses, debts-due, projected balance at 30 and 60 days
- FX-unavailable amounts shown in native currency with note
- Empty states suggest how to add data

---

#### P0.4 — Consolidate the two planned payment systems

*(Elevated from P1 — user confirmed `/upcoming` and morning digest already show different data.)*

**Problem:** `PlannedPayment` (read by daily digest) and `Transaction(is_planned=True)` (read by `/upcoming`) are separate tables. The split is invisible to the user.

**Why it matters:** All cashflow projection work (P0.3) must be built on one source of truth — otherwise projected balances will be wrong.

**Current evidence:**
- `finance_service.py::upcoming_transactions()` → `Transaction(is_planned=True)`
- `finance_service.py::upcoming_planned()` → `PlannedPayment`
- `daily_status_job.py` uses `upcoming_planned()` (PlannedPayment)
- `/upcoming` handler uses `upcoming_transactions()` (Transaction table)

**Proposed solution:** Consolidate onto `Transaction(is_planned=True)`. Steps:
1. One-time migration: convert existing `PlannedPayment` rows to `Transaction(is_planned=True, occurred_at=due_date)`
2. Update `daily_status_job.py` to use `upcoming_transactions()` instead of `upcoming_planned()`
3. Remove `PlannedPayment` write paths from bot handlers
4. Keep model class during migration period, mark deprecated

**Expected user outcome:** "What I see in `/upcoming` is what I get in the morning digest. Same list."

**Implementation complexity:** Medium — migration script + service consolidation.

**Risk:** Medium — needs a production check of existing `PlannedPayment` rows before migration.

**Dependencies:** Must complete before P0.3 (cashflow).

**Acceptance criteria:**
- `/upcoming` and daily digest show identical planned payments
- `PlannedPayment` write paths removed
- Migration script is idempotent
- No regression in `/upcoming` mark-paid flow

---

### P1 — High leverage improvements

---

#### P1.1 — `/review`: weekly financial review command

**Problem:** No single command exists for the weekly review. User must mentally combine `/month` + `/upcoming` + `/debts` + `/balances`.

**Why it matters:** The review is the decision engine. Without it the bot is a capture tool.

**Proposed solution:** `/review` assembles one message:
```
📋 Финансовый обзор — 02.05.2026

💼 Балансы: Наличные 12 000 ₽ · Тинькофф 38 500 ₽ · Всего ≈ 50 500 ₽

📥 Ожидается (30 дней): 25.05 · Зарплата · +80 000 ₽

📤 Запланировано: Netflix 49.90$ (15.05) · Аренда 30 000₽ (20.05)

📊 Переменные (факт): Продукты 8 200 / 12 000 ✅ · Кафе 4 100 / 3 000 🔴

💸 Долги: Пете 3 000 ₽ до 30.05

⚠️ Риски: Кафе +37% · 3 записи без тега

🔮 Прогноз к концу месяца: ~74 000 ₽

[🏷 Разобрать (3)]  [📅 Добавить план]
```

All data already exists — this is assembly, not new computation.

**Implementation complexity:** Medium — new handler + existing service calls.

**Risk:** Low. Degrades gracefully per section.

**Dependencies:** P0.2, P0.3 for projected balance.

**Acceptance criteria:**
- One message, all sections, each degrades gracefully if empty
- Renders in < 2 seconds
- Risk flags are actionable
- Inline buttons lead to /inbox and planned payment entry

---

#### P1.2 — Debt due-date reminders

**Problem:** `Debt.due_date` exists. `recurring_reminders.py` never checks it.

**Proposed solution:** Add ~15 lines to `recurring_reminders.py`: query `Debt` where `settled_at IS NULL AND due_date BETWEEN today AND today+3`. Send reminder. Use same EventLog 20-hour dedup.

**Implementation complexity:** Low.

**Risk:** Low.

**Acceptance criteria:**
- Debts with `due_date` within 3 days trigger Telegram reminder
- Shows direction (i_owe vs they_owe), counterparty, amount, due date
- Not re-sent within 20 hours
- Settled debts excluded

---

#### P1.3 — Previous month gap visibility

**Problem:** No way to see "what is incomplete in April?" before relying on its summary.

**Proposed solution:** `[✅ Проверить]` button on past months in `/month`. Click shows: consecutive days with zero transactions (≥3 highlighted), untagged count with /inbox link filtered to that month, planned payments that should have occurred but have no matching actual.

**Implementation complexity:** Medium.

**Dependencies:** None.

**Acceptance criteria:**
- Button visible on past months only
- Shows: zero-transaction day gaps, untagged count, missing expected payments
- /inbox link is pre-filtered to that month

---

### P2 — Useful but not urgent

#### P2.1 — Basic recurring payment management
`RecurringPayment` table exists, abandoned. `/recurring add Netflix 49.90 USD 15` to create; job auto-creates `Transaction(is_planned=True)` monthly. **Complexity: Medium. Depends on P0.4.**

#### P2.2 — Fix corrections page → primary_tag disconnect
`/finance/corrections` sets `category_id`; summaries use `primary_tag`. Replace category dropdown with tag input; write `primary_tag` on save. **Complexity: Low.**

#### P2.3 — `[📅 В план]` button for future-dated captures
When capture date > today, show a 4th inline button that sets `is_planned=True`. `inline_actions.py` already has the FSM state; just needs the trigger. **Complexity: Low. Depends on P0.4.**

---

### P3 — Parked / not now

| Item | Reason |
|---|---|
| `/ask` rate limiting | 2-person household cost is manageable |
| Fuzzy merchant matching | Exact match avoids false positives; auto-learn handles variance |
| LLM parse/meeting/digest contracts | Defined but unused; parse contract is actively dangerous (non-determinism in capture path) |
| SavingsGoal | No cashflow foundation yet |
| CategoryBudget | Superseded by TagBudget; clean up later |
| Task management module | Dormant, keep isolated |
| Bank integrations | Explicitly out of scope |
| Real-time FX rates | Daily CBR sufficient |

---

## Part 4 — Suggested MVP Sequence (7-day outcome)

**Goal: The bot can support a reliable 30–60 day personal finance map.**

```
День 1: Фундамент данных (всё дальнейшее зависит от этого)
  → P0.4: Консолидация систем planned payment (3-4ч)
    [Подтверждено: /upcoming и дайджест уже показывают разные данные]

День 2: Доверие к данным
  → P0.1: Подключить duplicate_handler (1-2ч)
  → P0.2: Поддержка planned income (2-3ч)

День 3-4: Ядро — кэшфлоу
  → P0.3: Команда /cashflow (4-5ч)
    Модель: балансы − плановые расходы + плановые доходы − долги с due_date

День 5-6: Слой обзора
  → P1.2: Напоминания о сроках долгов (1-2ч)
  → P1.1: Команда /review (4-5ч)

День 7: Снижение трения
  → P2.3: Кнопка [📅 В план] для будущих дат (1-2ч)
  → P2.2: Исправить corrections page → primary_tag (1-2ч)
```

**Итог:** `/cashflow` даёт карту на 30–60 дней. `/review` — еженедельный обзор в одной команде. Данные о планах в одном месте. Дубли запрашивают подтверждение. Напоминания о долгах работают. Финансовый контекст больше не нужно держать в голове.

**Отложено на следующий цикл:** P2.1 (recurring), P1.3 (gap visibility) — ценно, но не нужно для cashflow map.

---

## Part 5 — What NOT to Build Now

1. **LLM-based expense parsing** — детерминированный парсер корректно обрабатывает все известные паттерны. Добавление LLM в capture path вносит недетерминизм, задержки и стоимость.
2. **Bank integrations** — явное ограничение, правильное решение.
3. **Savings goal tracking** — цели без надёжного кэшфлоу декоративны.
4. **Task management coupling** — весь модуль спит, не связывать с финансами.
5. **AI-powered category suggestions** — autocat threshold-3 работает. LLM-предложения добавляют задержки и уверенные неправильные ответы.
6. **Multi-household support** — ноль пользы, значительная сложность.
7. **Budget forecasting / goal predictions** — качество данных недостаточно для прогнозов выше арифметики.
8. **Mobile app или web dashboard** — Telegram-first правильный выбор.

---

## Part 6 — Оставшиеся вопросы

*(Q1 и Q3 уже получены. Три остались.)*

**Q2. Ты сейчас вручную вводишь повторяющиеся фиксированные платежи (Netflix, аренда) каждый месяц, или пропускаешь их ввод?**
Это определяет, нужно ли двигать P2.1 (recurring payments) в P1.

**Q4. Есть ли данные в таблице `PlannedPayment` в production?**
Если да — нужен migration script перед P0.4. Если таблица пустая — консолидация займёт 1 час вместо 3.

**Q5. Важны ли тебе сроки возврата долгов? Ты сейчас их отслеживаешь?**
Если ты устанавливаешь `due_date` при вводе долгов — P1.2 немедленно ценен. Если нет — напоминания будут срабатывать на `NULL` (т.е. никогда) пока не изменишь привычку ввода.
