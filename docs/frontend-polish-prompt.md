# Prompt for Claude.ai web chat — UI polish for hastlefam dashboard

Copy everything below the `---` line into a fresh Claude.ai chat. Paste the full current template afterwards if Claude asks for it.

---

I have a private finance dashboard for a 2-person Russian household. It's a single Jinja2 template at `app/dashboard/templates/monthly_report.html` rendered by FastAPI. The data comes from a JSON island injected on the server. The dashboard is functional but has several rough edges. I want **incremental UI polish**, not a redesign — keep the existing block structure, just iterate on the weak spots.

## Tech constraints — must respect

- Single HTML file (Jinja2 template). No build step, no React, no bundler.
- Vanilla JavaScript only. The page already loads `Chart.js@4.4.4` via CDN — you can keep using it.
- Fonts loaded via Google Fonts: `Inter` (text), `JetBrains Mono` (numbers, tabular-nums).
- Dark theme — page background `#09090b`, text `#e4e4e7`, borders `#1f1f23`–`#3f3f46`, accent indigo `#6366f1`. Match these.
- All user-facing labels are in Russian.
- The data is already injected into the page as a JSON island; you don't need to add fetch logic for the main report data (only for the `/finance/report/range` endpoint, see below).
- Output should be **drop-in HTML/CSS/JS snippets** I can paste into the existing file. Tell me where each snippet replaces what.

## Existing block structure (monthly tab — the only one I want polished)

```
<header> — sticky top: brand, currency switcher (RUB|USD), tabs (Месяц/Квартал/Год/Годовой отчёт), period nav (‹ Май 2026 ›)
<main>
  <section id="tab-monthly">
    summary-cards  — hero "Текущий баланс" + per-account cards + 4 stat cards (Прогноз / Осталось / Потрачено / Требуют внимания)
    alerts-block   — overdue items (with inline ✓ оплачено / ⨯ пропустить buttons), mismatches, surprises
    income-card    — "Доходы" list (date · merchant · amount with dual-currency hint)
    cashflow card  — Chart.js with: line "Факт-баланс" (solid green), line "Прогноз-баланс" (dashed blue), bars "Доход" (green) and "Расход" (red) per day; today vertical reference; y-axis left=balance, y2-axis right=daily delta
    tag-analytics  — table: tag, total RUB, % of expenses, 31-day sparkline
    ledger         — filters (view: all|actual|planned, account dropdown, status dropdown) + table rows clickable to open side panel
  </section>
</main>
<aside id="side-panel"> — slide-in panel showing tx details
```

## Sample data shape (real response from /finance/report/data, truncated)

```json
{
  "year": 2026,
  "month": 5,
  "household_id": "ed36b994-...",
  "is_current_month": true,
  "balance_value_rub": 332774.24,
  "fx_rates": {"amd":0.1986, "usdt":73.13, "pln":20.02, "eur":85.18, "usd":73.13},
  "accounts": [
    {"id":"a1b2c3d4-...","name":"tm","currency":"RUB"},
    {"id":"4fca5a45-...","name":"Cash","currency":"RUB"},
    {"id":"a1b2c3d4-...","name":"tmcc","currency":"RUB"},
    {"id":"101e164a-...","name":"T-molly","currency":"USD"},
    {"id":"91b555f3-...","name":"USDT","currency":"USDT"}
  ],
  "snapshots": {
    "<account_id>": {"actual_balance": 95000.0, "as_of": "2026-04-01"}
  },
  "transactions": [
    {
      "id":"...","occurred_at":"2026-05-14","direction":"income",
      "amount":3481.26,"currency":"USDT","merchant_raw":"RevOps апрель",
      "primary_tag":"income_fix","account_id":"...",
      "is_planned":false,"is_internal_transfer":false,"status":"actual"
    },
    {
      "id":"...","occurred_at":"2026-04-10","direction":"expense",
      "amount":80200.0,"currency":"RUB","merchant_raw":"tmcc беспроцентный платёж",
      "primary_tag":"loan","account_id":"...",
      "is_planned":true,"is_internal_transfer":false,"status":"overdue"
    }
  ],
  "tag_summary": [
    {"tag":"food","total_rub":18728.0},
    {"tag":"(без тега)","total_rub":16107.0}
  ]
}
```

Volume in practice: 4–6 accounts, 40–80 transactions per month, ~15 tags, 5 currencies.

Status values for transactions: `actual`, `planned`, `overdue`, `mismatch`, `unplanned`. Direction values: `income`, `expense`. (Transfers and exchanges are filtered server-side.)

For the **Quarter/Year/Annual** tabs there's an additional endpoint `/finance/report/range?household_id=X&from=YYYY-MM&to=YYYY-MM` that returns:
```json
{"months":[{"yr":2026,"mo":5,"actual_income_rub":266046.84,"actual_expense_rub":62272.01}, ...]}
```

## Pain points — these are what I want polished

1. **Cashflow chart looks busy and confusing.**
   - Mixing two lines (actual + forecast) and two bar series (income + expense) on a 31-day x-axis. Hard to read.
   - The vertical "today" reference is missing.
   - When viewing a past month, the forecast line is meaningless but still drawn.
   - Bars are tiny because there are 31 day-slots even for sparse data.
   - I want a clearer, less-cluttered visualization. Single line for balance over time, daily deltas as compact diverging bars below it (income +, expense −), today marker prominent. Past-month view should drop the forecast entirely.

2. **Currency switching is half-applied.**
   - Top-right RUB↔USD toggle changes some numbers (hero, totals, chart axes) but native amounts in the ledger and Доходы lists stay native, with a `(RUB equivalent)` hint appended when mismatched.
   - This dual display creates visual noise. I want one consistent rule. Either: (a) always show native + small RUB tooltip on hover, or (b) globally convert when toggle is set, no dual display.
   - Propose the rule and apply it everywhere.

3. **Tag analytics is a wall of bars.**
   - It's a table: tag, total, %, 31-day sparkline. The sparkline is hard to interpret without scale.
   - There's no concept of "compared to last month".
   - Top 3 tags absorb most attention; tags with tiny totals feel like clutter.
   - Make it scan-able at a glance. Suggestion welcomed: maybe a treemap, maybe collapsing tags under 1% into "other", maybe a sortable header.

4. **Mobile / narrow viewports break the layout.**
   - Cards wrap into vertical stacks but look weird because of `flex:2 1 280px` on the hero.
   - The ledger table overflows horizontally below ~700px viewport (7 columns + action buttons).
   - The side panel on mobile should be a bottom sheet, not a sidebar.
   - I check this on phone often. Mobile should be first-class.

5. **Visual hierarchy: hero balance card competes with per-account cards.**
   - The hero is supposed to be THE number. But it's in the same row as 5 other cards of similar size. Eye doesn't land on it first.
   - Make the hero unambiguously dominant. Per-account cards should feel like supporting detail.

6. **Alerts block can take 30%+ of viewport when many overdue items.**
   - Each overdue row is full-width with two action buttons. 12 overdue items = ~400px of scroll before the user sees the chart.
   - Collapse to "12 просроченных · показать" by default; expand on click. Or show first 3, with "+9 more".

## Output format — for each pain point above

Give me:
1. **Diagnosis** (1 sentence — what's actually causing the issue)
2. **Proposed fix** (2-3 bullets — the approach)
3. **Drop-in code** — exact HTML/CSS/JS snippet I can paste in, with a `// REPLACE: existing function renderCashflowChart()` style comment at the top so I know where it goes.
4. **(Optional) ASCII mockup** if visual layout changes.

Order them 1→6 as listed. If two pain points share a fix, group them.

## What NOT to touch

- Server-side code (FastAPI routes, Supabase REST queries, RPC functions) — frontend only.
- The shape of the injected JSON — work with what's listed above.
- Authentication (HTTP Basic Auth middleware) — leave alone.
- Don't introduce a build step, npm dependencies, React/Vue/anything. Vanilla JS + CDN Chart.js is the limit.
- Don't change the Russian language. Don't romanize labels.
- Don't change the URL structure or query params (`?household_id=X&month=YYYY-MM`).

## One question before you start

If anything in the data shape or block structure is ambiguous, ask me before generating code. Otherwise dive in.
