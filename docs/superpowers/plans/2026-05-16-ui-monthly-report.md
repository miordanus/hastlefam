# UI: Monthly Accounting Report & Cashflow — Implementation Plan

## What exists now

**Frontend:** Two Jinja2 HTML templates only.
- `app/dashboard/templates/index.html` — bare link list, no styling
- `app/dashboard/templates/finance_corrections.html` — simple correction form
- No React, no Tailwind, no build system, no package.json

**Relevant backend routes:**
- `GET /finance/month?household_id=` — MTD summary dict
- `GET /finance/upcoming?household_id=&days=7` — upcoming recurring payments

**Real data model (grounded in `all_models.py`):**

| Entity | Key fields | Notes |
|---|---|---|
| `Account` | id, name, currency, is_shared, is_active | No `current_balance` stored — derived from snapshots |
| `Transaction` | id, direction, amount, currency, occurred_at, merchant_raw, is_planned, is_internal_transfer, account_id, primary_tag | `is_planned=True` = planned entry; no `status` field; no `running_expected_balance` |
| `PlannedPayment` | id, title, amount, currency, due_date, primary_tag, status, linked_transaction_id | Legacy table; `linked_transaction_id` is the match link |
| `RecurringPayment` | id, title, amount_expected, currency, next_due_date, cadence | No `account_id` |
| `BalanceSnapshot` | account_id, actual_balance, created_at | Manual checkpoints only — no auto-computed running balance |

## What is missing (vs the brief)

| Gap | Impact |
|---|---|
| No `running_expected_balance` on Transaction | Must compute client-side from sorted transactions + starting snapshot |
| No `status` field (matched/overdue/mismatch/unplanned) | Must derive: planned tx with `linked_transaction_id` = matched; planned past due date = overdue; actual with no plan link = unplanned |
| No `linked_planned_transaction_id` on Transaction | PlannedPayment.linked_transaction_id goes the other direction — workable |
| No `current_balance` on Account | Use latest BalanceSnapshot per account |
| No cashflow/chart API endpoint | Frontend computes from combined planned+actual tx list |
| No React frontend | Standalone prototype file only |

## Approach

**Prototype delivery:** Single self-contained HTML file at `app/dashboard/templates/monthly_report.html`.
- React 18 via CDN (babel-standalone for JSX)
- Tailwind CSS via CDN
- Recharts via CDN (UMD build)
- lucide-react icons via CDN
- All mock data inline — clearly marked `MOCK`
- FastAPI can serve it at `/finance/report` with zero build step

**No new backend routes needed for the prototype.** Mock data is faithful to real schema field names so wiring to real API later is straightforward.

## Status derivation logic (pure frontend)

```
Transaction.is_planned=True, occurred_at > today             → "planned"
Transaction.is_planned=True, occurred_at <= today,
  PlannedPayment.linked_transaction_id exists                 → "matched"
Transaction.is_planned=True, occurred_at < today,
  no linked_transaction_id                                    → "overdue"
Transaction.is_planned=False, is_internal_transfer=False,
  amount ≠ planned_amount (tolerance > 5%)                   → "mismatch"
Transaction.is_planned=False, no linked planned tx           → "unplanned"
Transaction.is_planned=False, linked planned tx exists       → "actual" (normal)
```

## Running balance computation

```
starting_balance = latest BalanceSnapshot for account (or 0 if none)
sort all entries (planned + actual) by date ascending
walk list: running_balance += income_amount OR -= expense_amount
```

## Components

1. `SummaryBar` — sticky top: starting bal / actual today / forecast end / planned remaining / unreconciled count
2. `FiltersBar` — month picker, account filter, currency filter, status filter, toggle actual/planned/both
3. `CashflowChart` — Recharts ComposedChart: area (actual balance), dashed line (forecast), bars (daily income/expense)
4. `LedgerTable` — chronological rows, status badge, amount, running balance column
5. `TransactionPanel` — slide-in side panel on row click
6. `AlertsBlock` — overdue / below-zero / unreconciled warnings

## Mock data design

Faithfully uses real field names. May 2026. Two accounts: Тинькофф (RUB), USD Cash.
Mix of: actual expenses, planned rent (overdue), matched subscription, upcoming salary, unplanned coffee run.

## Backend wiring needed later

1. `/finance/report?household_id=&month=2026-05` — returns `{accounts, transactions, planned_payments, balance_snapshots}`
2. Frontend computes derived fields (status, running_balance) — keep computation in JS, don't push to backend
3. PlannedPayment.linked_transaction_id → index for O(1) match lookup

## File to create

`app/dashboard/templates/monthly_report.html` — the prototype
`app/api/routers/finance.py` — add `GET /finance/report` route (later, post-prototype)

## Design language

- Background: zinc-950 or slate-950 (dark-first)
- Cards: zinc-900 with zinc-800 border
- Status badges: color-coded (green=actual, blue=planned, amber=overdue, red=mismatch, purple=matched, gray=unplanned)
- Numbers: tabular-nums, right-aligned, large weight for totals
- Running balance column: dim color until today, forecast color after
- Danger zone: red tint on rows where running balance < 0
