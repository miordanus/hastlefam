# Dashboard Tabs Restructure (QoQ + YoY) — Design

**Date:** 2026-05-24
**Status:** Approved (verbal)
**Target file:** `app/dashboard/templates/monthly_report.html` + `app/api/routers/finance.py` + `app/application/services/finance_service.py`

## Problem

Three issues on the deployed dashboard (`/finance/report`):

1. **Quarter switcher is broken.** Clicking `‹/›` on the Quarterly tab does navigate by 3 months, but the page reload resets `activeTab` to `monthly` — so the user ends up on the Monthly tab with the new period instead of seeing the new quarter.
2. **Quarterly tab is summary-only.** Today: 3-month breakdown + Q totals. No comparison to the prior quarter.
3. **Yearly and Annual tabs overlap.** Both show this-year data; Annual is just a narrative version of Yearly's totals. No YoY comparison anywhere.

## Goals

- Fix tab persistence across reloads/period nav.
- Make Quarterly tab QoQ-first: this quarter vs prior quarter.
- Repurpose Annual ("Годовой отчёт") as YoY: this year vs prior year, with the narrative inset preserved.
- Add a "category movers" backend that the redesigned tabs consume.
- Monthly, Yearly, Cashflow tabs unchanged.

## Non-goals

- No new Monthly-tab features.
- No income movers (Q4 decision: expense-only).
- No automatic insights/LLM commentary on the deltas.
- Local SQLAlchemy fallback for the new endpoint — Vercel REST only, same posture as `/finance/report/range`.

## Design

### 1. Tab state persistence

URL gains `?tab=monthly|quarterly|yearly|annual|cashflow`.

- `switchTab(tab)` updates the URL via `history.replaceState` (no reload) and triggers `renderActiveTab()`.
- `navPeriod(delta)` carries the current `tab` value in the next URL.
- On boot, before any render, read `?tab=` and set `activeTab` (default `monthly` for back-compat).

### 2. Quarterly tab layout

```
Q2 2026                                                ‹ Q2 2026 ›

[hero]   Сальдо квартала
         +438 240 ₽           ▲ +38% vs Q1 2026
         доход 850k · расход 412k · норма 52%

[compare]               Q1 2026      Q2 2026         Δ
         Доходы           759k          850k       +12%
         Расходы          430k          412k        −4%
         Сальдо           328k          438k       +33%
         Норма             43%           52%       +9pp

[movers] Движения по категориям расходов
         ↑ Выросли                       ↓ Сократились
         #путешествия  +84k  +220%       #рестораны   −48k  −32%
         #электроника  +62k  +180%       #такси       −18k  −51%
         #жкх          +15k   +12%       #подписки     −9k  −18%
         #продукты      +8k    +7%       #бытовые      −5k   −8%
         #транспорт     +4k    +9%       #разное       −4k  −16%

[months] Апрель      +270k  −135k  +135k   50%
         Май         +290k  −160k  +130k   45%
         Июнь        +290k  −117k  +173k   60%  ← текущий
         Итого Q2    +850k  −412k  +438k   52%
```

### 3. Annual ("Годовой отчёт") layout

Same zones as Quarterly, applied year-vs-year, plus the existing narrative inset (best/worst month, monthly avg) kept only here.

```
[hero]    Сальдо года 2026
          +1 420 000 ₽        ▲ +24% vs 2025
          доход 3.2M · расход 1.8M · норма 44%
[compare] 2025 / 2026 / Δ
[movers]  ↑ / ↓ by expense tag (YoY)
[insights] 📈 лучший месяц · 💸 самый расходный · 📊 месяцев с данными · 💰 средний доход/расход
```

The "best month / worst month" inset is removed from the Yearly tab (it's purely visual there via the bar chart; the narrative belongs with the comparison view).

### 4. Backend: new endpoint

**`GET /finance/category_movers`**

Params:

| Name | Type | Notes |
|---|---|---|
| `household_id` | str (UUID) | required |
| `from` | str | YYYY-MM, current period start (inclusive) |
| `to` | str | YYYY-MM, current period end (inclusive) |
| `prev_from` | str | YYYY-MM, prior period start (inclusive) |
| `prev_to` | str | YYYY-MM, prior period end (inclusive) |

(`direction` is hardcoded to `expense` for v1 per scope.)

Response:

```json
{
  "current": { "from": "2026-04", "to": "2026-06", "total_rub": 412000 },
  "prior":   { "from": "2026-01", "to": "2026-03", "total_rub": 430000 },
  "movers": [
    { "tag": "путешествия", "current_rub": 122000, "prior_rub": 38000,
      "delta_rub": 84000, "delta_pct": 221 },
    { "tag": "рестораны", "current_rub": 102000, "prior_rub": 150000,
      "delta_rub": -48000, "delta_pct": -32 }
  ]
}
```

Movers sorted by `abs(delta_rub)` descending. Frontend trims to top 5 ↑ + top 5 ↓.

Implementation: Vercel REST path only. Fetches transactions in `[prev_from..to]` with `direction=expense`, `is_planned=false`, `is_internal_transfer=false`, `is_skipped=false`. Converts each row to RUB using latest rates from `fx_rates` (mirror `monthly_report_via_rest`'s FX path). Groups by `primary_tag` (NULL → `(без тега)`). Returns `503` if REST not configured.

### 5. Frontend changes

- `renderQuarterly()` rewritten: parallel `fetch` of `/finance/report/range` (3 months) + `/finance/category_movers` (current Q vs prior Q). Renders hero → compare → movers → months.
- `renderAnnual()` rewritten the same way with year ranges + insights inset.
- New helpers in JS:
  - `_qPrevRange(year, month)` / `_yPrevRange(year)` — compute prior-period bounds.
  - `_compareTable({prior, current})` — renders the 4-row compare block.
  - `_moversList(movers)` — renders the two-column ↑/↓ block.
  - `_pctChip(deltaPct, options)` — small Δ chip used by hero + compare + movers.
- HTML for `tab-quarterly` and `tab-annual` re-generated to match the new zones. Existing element ids (`q-stats`, `q-body`, `a-summary`, etc.) replaced by the new zones; nothing else references them.

### 6. Edge cases

- **Prior period has no data:** compare table shows `—` for the prior column and `—` (not `+∞`) for Δ. Movers block renders `"Нет данных за прошлый период"`.
- **No expense transactions at all in either period:** movers block renders `"Нет расходов"`.
- **Tag had 0 in prior period** (newly used category): `delta_pct = null`; UI renders a `новая` badge instead of a percent.
- **Tag had spending in prior, 0 in current** (disappeared category): `delta_pct = -100`; UI renders normally as `−100%`. Still eligible for the ↓ column.
- **Sign convention:** `delta_rub = current_rub - prior_rub`. Positive = grew, negative = shrank. Sort by `abs(delta_rub)` desc.
- **Current period is partial** (today is mid-quarter / mid-year): hero meta line ends with `· к настоящему моменту`. Compare table still uses partial actuals — we do not annualize/normalize.
- **REST not configured (local Postgres):** endpoint returns `503`; frontend shows `"Доступно только при работе через Supabase REST"` in the movers zone. The hero/compare/months zones use `/finance/report/range` which already 503s in this case — so behavior is consistent: tab is essentially Vercel-only, same as today.

### 7. Testing

- Backend: unit test the `category_movers` aggregation against a small SQLite fixture (mock REST off and test via direct SQLAlchemy variant if added; otherwise integration-test against a seeded Supabase REST in dev).
- Frontend: manual verification on Vercel. Click each tab from each tab, hit `‹/›`, refresh, confirm tab stays, data populates, edge cases (Jan 2026 → prior Q is Q4 2025) work.

## Out-of-scope follow-ups

- Local SQLAlchemy variant of `/finance/category_movers` (so the tabs work outside Vercel).
- Income movers (Q4: scope deferred).
- LLM-narrated insights on QoQ shifts.
- Visual sparkline showing 5+ quarters of trend (an earlier alternative in brainstorming; not picked).

## Estimate

~90 min total: backend ~30, tab persistence ~10, two render rewrites ~40, edge cases + Vercel verification ~10.
