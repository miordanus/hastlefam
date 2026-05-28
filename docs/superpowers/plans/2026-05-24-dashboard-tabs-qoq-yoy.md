# Dashboard Tabs QoQ + YoY Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the Quarterly and Annual tabs to be comparison-first (QoQ / YoY), add an expense "category movers" backend endpoint, and make tab state survive period nav reloads.

**Architecture:** One new REST-mode backend method + route (`/finance/category_movers`) that aggregates per-tag expense across two adjacent periods. Frontend rewrites two render functions and adds a shared compare-table / movers-list helper. Tab state moves into the URL (`?tab=`) so `navPeriod` reloads land on the same tab.

**Tech Stack:** FastAPI, SQLAlchemy-skipping REST path via `SupabaseClient` (PostgREST), aiogram unaffected, vanilla JS + Chart.js in `monthly_report.html`.

**Spec:** `docs/superpowers/specs/2026-05-24-dashboard-tabs-redesign.md`

**Branch:** `feat/dashboard-tabs-qoq-yoy` (already checked out, spec committed).

**Deploy posture:** Vercel REST only. No local SQLAlchemy fallback for the new endpoint (consistent with `/finance/report/range`).

---

## File map

| File | What changes |
|---|---|
| `app/application/services/finance_service.py` | Add `category_movers_via_rest()` method. |
| `app/api/routers/finance.py` | Add `GET /finance/category_movers` route. |
| `app/dashboard/templates/monthly_report.html` | Replace `tab-quarterly` + `tab-annual` HTML; add JS helpers; rewrite `renderQuarterly` and `renderAnnual`; URL-persisted tab state. |

Tests: existing REST-mode service methods (`monthly_report_via_rest`, `cashflow_monthly_via_rest`) ship without unit tests in this repo. To stay consistent we will rely on a manual Vercel smoke (Task 8). If a test pattern emerges in a follow-up PR, the new method can be back-tested.

---

## Task 1: Backend — `category_movers_via_rest()` service method

**Files:**
- Modify: `app/application/services/finance_service.py` (append a new method near the existing `cashflow_monthly_via_rest`)

- [x] **Step 1: Add the method to `FinanceService`**

Append after the existing `cashflow_monthly_via_rest` method (or anywhere among the `*_via_rest` methods):

```python
    # ─── Category movers (QoQ / YoY) ─────────────────────────────────────────

    def category_movers_via_rest(
        self,
        household_id: str,
        period_from: str,   # YYYY-MM, current period start
        period_to: str,     # YYYY-MM, current period end
        prev_from: str,     # YYYY-MM, prior period start
        prev_to: str,       # YYYY-MM, prior period end
    ) -> dict[str, Any]:
        """Per-tag expense aggregates across two adjacent periods (RUB-converted).

        Returns {"current": {...}, "prior": {...}, "movers": [...]} where movers is
        sorted by abs(delta_rub) descending. Vercel/REST-only — same posture as
        /finance/report/range. Filters: direction=expense, is_planned=false,
        is_internal_transfer=false, is_skipped=false.
        """
        from app.infrastructure.config.settings import get_settings
        from app.infrastructure.supabase import SupabaseClient
        import calendar as _cal
        import datetime as _dt

        def _ym_bounds(ym_from: str, ym_to: str) -> tuple[str, str]:
            fy, fm = [int(x) for x in ym_from.split("-")]
            ty, tm = [int(x) for x in ym_to.split("-")]
            start = _dt.date(fy, fm, 1).isoformat()
            end = _dt.date(ty, tm, _cal.monthrange(ty, tm)[1]).isoformat()
            return start, end

        curr_start, curr_end = _ym_bounds(period_from, period_to)
        prev_start, prev_end = _ym_bounds(prev_from, prev_to)
        # PostgREST range covers both windows; filter into buckets in Python.
        full_start = min(curr_start, prev_start)
        full_end = max(curr_end, prev_end)

        s = get_settings()
        with SupabaseClient(s.supabase_url, s.supabase_service_role_key) as sb:
            txs = sb.get("transactions", {
                "select": "occurred_at,amount,currency,primary_tag",
                "household_id": f"eq.{household_id}",
                "direction": "eq.expense",
                "is_planned": "eq.false",
                "is_internal_transfer": "eq.false",
                "is_skipped": "eq.false",
                "occurred_at": [f"gte.{full_start}", f"lte.{full_end}"],
            })
            fx_rows = sb.get("fx_rates", {
                "select": "from_currency,rate,date",
                "to_currency": "eq.RUB",
                "order": "date.desc",
                "limit": "60",
            })

        fx_latest: dict[str, float] = {}
        for r in fx_rows:
            cur = (r.get("from_currency") or "").lower()
            if cur and cur not in fx_latest:
                fx_latest[cur] = float(r["rate"])

        def _to_rub(amount: float, cur: str | None) -> float:
            c = (cur or "rub").lower()
            if c == "rub":
                return amount
            if c == "usdt":
                c = "usd"
            return amount * fx_latest.get(c, 1.0)

        curr_by_tag: dict[str, float] = {}
        prior_by_tag: dict[str, float] = {}
        curr_total = 0.0
        prior_total = 0.0

        for tx in txs:
            occ = (tx.get("occurred_at") or "")[:10]
            amount_rub = _to_rub(float(tx["amount"]), tx.get("currency"))
            tag = tx.get("primary_tag") or "(без тега)"
            if curr_start <= occ <= curr_end:
                curr_by_tag[tag] = curr_by_tag.get(tag, 0.0) + amount_rub
                curr_total += amount_rub
            elif prev_start <= occ <= prev_end:
                prior_by_tag[tag] = prior_by_tag.get(tag, 0.0) + amount_rub
                prior_total += amount_rub

        all_tags = set(curr_by_tag.keys()) | set(prior_by_tag.keys())
        movers: list[dict[str, Any]] = []
        for tag in all_tags:
            c = curr_by_tag.get(tag, 0.0)
            p = prior_by_tag.get(tag, 0.0)
            delta = c - p
            if p > 0:
                delta_pct: int | None = round(delta / p * 100)
            elif c > 0:
                delta_pct = None   # newly used category
            else:
                continue            # both zero — skip
            movers.append({
                "tag": tag,
                "current_rub": c,
                "prior_rub": p,
                "delta_rub": delta,
                "delta_pct": delta_pct,
            })

        movers.sort(key=lambda m: abs(m["delta_rub"]), reverse=True)

        return {
            "current": {"from": period_from, "to": period_to, "total_rub": curr_total},
            "prior":   {"from": prev_from,   "to": prev_to,   "total_rub": prior_total},
            "movers":  movers,
        }
```

- [x] **Step 2: Syntax-check**

Run: `python3 -m py_compile app/application/services/finance_service.py`
Expected: silent success (no traceback).

- [x] **Step 3: Commit**

```bash
git add app/application/services/finance_service.py
git commit -m "feat(finance): add category_movers_via_rest for QoQ/YoY analysis

Aggregates per-tag expense across two adjacent periods, FX-converted to
RUB using latest fx_rates rows. Returns sorted-by-abs(delta) movers with
explicit handling for newly-used categories (delta_pct=null)."
```

---

## Task 2: Backend — `/finance/category_movers` route

**Files:**
- Modify: `app/api/routers/finance.py` (append a new route after `/finance/report/range`)

- [x] **Step 1: Add the route**

Append after the `report_range` function (end of file):

```python


@router.get("/category_movers")
def category_movers(
    household_id: str = Query(...),
    from_:     str = Query(..., alias="from",      description="YYYY-MM, current period start"),
    to_:       str = Query(..., alias="to",        description="YYYY-MM, current period end"),
    prev_from: str = Query(..., alias="prev_from", description="YYYY-MM, prior period start"),
    prev_to:   str = Query(..., alias="prev_to",   description="YYYY-MM, prior period end"),
) -> dict:
    """Top expense-category movers across two adjacent periods (REST-only)."""
    if not _use_rest():
        raise HTTPException(status_code=503, detail="Supabase REST not configured")
    for ym in (from_, to_, prev_from, prev_to):
        try:
            y, m = [int(x) for x in ym.split("-")]
            if not (1 <= m <= 12):
                raise ValueError
        except ValueError:
            raise HTTPException(status_code=422, detail="period bounds must be YYYY-MM")
    return FinanceService(None).category_movers_via_rest(
        household_id, from_, to_, prev_from, prev_to
    )
```

- [x] **Step 2: Syntax-check**

Run: `python3 -m py_compile app/api/routers/finance.py`
Expected: silent success.

- [x] **Step 3: Commit**

```bash
git add app/api/routers/finance.py
git commit -m "feat(api): GET /finance/category_movers endpoint

Validates YYYY-MM bounds, delegates to category_movers_via_rest.
Returns 503 if SUPABASE_URL/SERVICE_ROLE_KEY not configured (matches
/finance/report/range)."
```

---

## Task 3: Frontend — replace HTML for `tab-quarterly` and `tab-annual`

**Files:**
- Modify: `app/dashboard/templates/monthly_report.html` (lines ~363–402 for the existing Quarterly/Yearly/Annual blocks; we touch Quarterly + Annual only)

- [x] **Step 1: Replace the Quarterly tab block**

Find:

```html
  <!-- ═══ QUARTERLY ═══ -->
  <div class="tab-view" id="tab-quarterly">
    <div class="hero">
      <div class="hero-label">Квартал</div>
      <div class="hero-amount mono" id="q-title">—</div>
      <div class="hero-meta"><span class="hero-meta-muted" id="q-range">—</span></div>
    </div>
    <div class="stat-grid" id="q-stats"></div>
    <div class="cardv">
      <div class="cardv-head"><span class="cardv-title">Помесячно</span></div>
      <div class="ledger-wrap">
        <table class="ledger-table">
          <thead><tr><th>Месяц</th><th class="r">Доходы</th><th class="r">Расходы</th><th class="r">Нетто</th><th class="r">Норма сбережений</th></tr></thead>
          <tbody id="q-body"></tbody>
        </table>
      </div>
    </div>
  </div>
```

Replace with:

```html
  <!-- ═══ QUARTERLY (QoQ) ═══ -->
  <div class="tab-view" id="tab-quarterly">
    <div class="hero" id="q-hero">
      <div class="hero-label" id="q-hero-label">Сальдо квартала</div>
      <div class="hero-amount mono" id="q-hero-amount">—</div>
      <div class="hero-meta" id="q-hero-meta"></div>
    </div>
    <div class="cardv">
      <div class="cardv-head"><span class="cardv-title">Сравнение с прошлым кварталом</span></div>
      <div id="q-compare"></div>
    </div>
    <div class="cardv">
      <div class="cardv-head"><span class="cardv-title">Движения по категориям расходов</span></div>
      <div id="q-movers"></div>
    </div>
    <div class="cardv">
      <div class="cardv-head"><span class="cardv-title">Помесячно</span></div>
      <div class="ledger-wrap">
        <table class="ledger-table">
          <thead><tr><th>Месяц</th><th class="r">Доходы</th><th class="r">Расходы</th><th class="r">Сальдо</th><th class="r">Норма сбережений</th></tr></thead>
          <tbody id="q-body"></tbody>
        </table>
      </div>
    </div>
  </div>
```

- [x] **Step 2: Replace the Annual tab block**

Find:

```html
  <!-- ═══ ANNUAL ═══ -->
  <div class="tab-view" id="tab-annual">
    <div class="hero">
      <div class="hero-label">Годовой отчёт</div>
      <div class="hero-amount mono" id="a-title">—</div>
      <div class="hero-meta"><span class="hero-meta-muted">итоги года</span></div>
    </div>
    <div class="stat-grid" id="a-stats"></div>
    <div class="cardv">
      <div class="cardv-head"><span class="cardv-title">Сводка</span></div>
      <div id="a-summary" style="padding:18px 20px;color:var(--muted);font-size:13px;"></div>
    </div>
  </div>
```

Replace with:

```html
  <!-- ═══ ANNUAL (YoY) ═══ -->
  <div class="tab-view" id="tab-annual">
    <div class="hero" id="a-hero">
      <div class="hero-label" id="a-hero-label">Сальдо года</div>
      <div class="hero-amount mono" id="a-hero-amount">—</div>
      <div class="hero-meta" id="a-hero-meta"></div>
    </div>
    <div class="cardv">
      <div class="cardv-head"><span class="cardv-title">Сравнение с прошлым годом</span></div>
      <div id="a-compare"></div>
    </div>
    <div class="cardv">
      <div class="cardv-head"><span class="cardv-title">Движения по категориям расходов</span></div>
      <div id="a-movers"></div>
    </div>
    <div class="cardv">
      <div class="cardv-head"><span class="cardv-title">Сводка</span></div>
      <div id="a-summary" style="padding:18px 20px;color:var(--muted);font-size:13px;"></div>
    </div>
  </div>
```

- [x] **Step 3: Add CSS for the compare-table and movers-list zones**

Find the `/* ── Section card (quarter/year/annual placeholders) ── */` block and add the following AFTER its `.placeholder` rule, before `</style>`:

```css
/* ── Compare table (Q1 vs Q2 / 2025 vs 2026) ───────────────────────────── */
.cmp-table { width:100%; border-collapse:collapse; }
.cmp-table th { font-size:10px; color:var(--border2); text-transform:uppercase; letter-spacing:0.07em; padding:10px 16px; text-align:right; }
.cmp-table th.l { text-align:left; }
.cmp-table td { padding:10px 16px; border-top:1px solid var(--surface2); font-size:13px; text-align:right; font-family:'JetBrains Mono',monospace; font-variant-numeric:tabular-nums; }
.cmp-table td.l { text-align:left; font-family:'Inter',system-ui,sans-serif; color:#a1a1aa; }
.cmp-delta.pos { color:var(--green); }
.cmp-delta.neg { color:var(--red); }
.cmp-delta.flat { color:var(--muted); }

/* ── Movers list (↑ outgrew / ↓ shrunk) ────────────────────────────────── */
.mv-grid { display:grid; grid-template-columns:1fr 1fr; gap:0; }
.mv-col { padding:12px 16px; }
.mv-col + .mv-col { border-left:1px solid var(--surface2); }
.mv-col-head { font-size:11px; color:var(--subtle); text-transform:uppercase; letter-spacing:0.07em; margin-bottom:8px; display:flex; align-items:center; gap:6px; }
.mv-row { display:flex; align-items:center; gap:8px; padding:5px 0; font-size:13px; }
.mv-tag { flex:1; color:var(--text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.mv-amt { font-family:'JetBrains Mono',monospace; font-variant-numeric:tabular-nums; min-width:64px; text-align:right; color:#a1a1aa; }
.mv-pct { font-family:'JetBrains Mono',monospace; min-width:54px; text-align:right; font-size:11px; }
.mv-pct.pos { color:var(--green); }
.mv-pct.neg { color:var(--red); }
.mv-pct.new { background:rgba(99,102,241,0.18); color:var(--accent); padding:1px 6px; border-radius:3px; font-weight:600; }
.mv-empty { color:var(--subtle); font-size:12px; padding:6px 0; }
@media (max-width:640px) {
  .mv-grid { grid-template-columns:1fr; }
  .mv-col + .mv-col { border-left:none; border-top:1px solid var(--surface2); }
}

/* ── Hero QoQ/YoY chip ─────────────────────────────────────────────────── */
.delta-chip { display:inline-flex; align-items:center; gap:4px; font-size:12px; padding:3px 9px; border-radius:14px; font-family:'JetBrains Mono',monospace; font-variant-numeric:tabular-nums; margin-left:10px; vertical-align:middle; }
.delta-chip.pos { background:rgba(34,197,94,0.14); color:var(--green); border:1px solid rgba(34,197,94,0.35); }
.delta-chip.neg { background:rgba(239,68,68,0.14); color:var(--red); border:1px solid rgba(239,68,68,0.35); }
.delta-chip.flat { background:var(--surface2); color:var(--muted); border:1px solid var(--border); }
```

- [x] **Step 4: Commit**

```bash
git add app/dashboard/templates/monthly_report.html
git commit -m "feat(web): new QoQ/YoY HTML zones + CSS for Quarterly/Annual tabs

Replaces the old stat-grid + single-table layout with hero / compare /
movers / months zones. Adds .cmp-table, .mv-grid, .delta-chip styles."
```

---

## Task 4: Frontend — shared JS helpers

**Files:**
- Modify: `app/dashboard/templates/monthly_report.html` (insert helpers near the existing `loadRange` / Quarterly helpers section, around line ~1180)

- [x] **Step 1: Add the helpers**

Insert immediately AFTER the `loadRange` function (just before `async function renderQuarterly`):

```javascript
// ─── Shared helpers for QoQ / YoY zones ────────────────────────────────────

function _qPrevRange(year, month) {
  // Given a month inside Qx, return [{fromYM, toYM}] for Qx-1 and Qx.
  const qStart = Math.floor((month - 1) / 3) * 3 + 1;
  const qEnd = qStart + 2;
  const prevQStart = qStart - 3, prevQEnd = qEnd - 3;
  const norm = (y, m) => {
    while (m < 1)  { m += 12; y--; }
    while (m > 12) { m -= 12; y++; }
    return { y, m };
  };
  const a = norm(year, prevQStart), b = norm(year, prevQEnd);
  const c = norm(year, qStart),     d = norm(year, qEnd);
  const ym = ({y, m}) => `${y}-${String(m).padStart(2,'0')}`;
  return {
    curr:  { from: ym(c), to: ym(d), label: `Q${Math.ceil(qStart/3)} ${c.y}` },
    prior: { from: ym(a), to: ym(b), label: `Q${Math.ceil(prevQStart<=0?(prevQStart+12)/3:prevQStart/3)} ${a.y}` },
  };
}

function _yPrevRange(year) {
  const ym = (y, m) => `${y}-${String(m).padStart(2,'0')}`;
  return {
    curr:  { from: ym(year,1),   to: ym(year,12),   label: `${year}` },
    prior: { from: ym(year-1,1), to: ym(year-1,12), label: `${year-1}` },
  };
}

function _pctChip(deltaPct, opts = {}) {
  // opts.unit: '%' or 'pp' (percentage points, for savings-rate delta)
  // opts.flatThreshold: |Δ| below this renders flat-styled
  const unit = opts.unit || '%';
  const ft   = (opts.flatThreshold != null) ? opts.flatThreshold : 1;
  if (deltaPct == null || isNaN(deltaPct)) return `<span class="delta-chip flat">—</span>`;
  const sign = deltaPct > 0 ? '▲ +' : deltaPct < 0 ? '▼ ' : '';
  const cls  = Math.abs(deltaPct) < ft ? 'flat' : (deltaPct > 0 ? 'pos' : 'neg');
  return `<span class="delta-chip ${cls}">${sign}${deltaPct}${unit}</span>`;
}

function _safePct(curr, prior) {
  if (prior === 0 || prior == null) return null;
  return Math.round((curr - prior) / prior * 100);
}

function _compareTable({ priorLabel, currLabel, prior, curr }) {
  // prior/curr: { income_rub, expense_rub }
  const incΔ  = _safePct(curr.income_rub, prior.income_rub);
  const expΔ  = _safePct(curr.expense_rub, prior.expense_rub);
  const netP  = prior.income_rub - prior.expense_rub;
  const netC  = curr.income_rub - curr.expense_rub;
  const netΔ  = _safePct(netC, netP);
  const savP  = prior.income_rub > 0 ? Math.round(netP / prior.income_rub * 100) : null;
  const savC  = curr.income_rub > 0  ? Math.round(netC / curr.income_rub * 100)  : null;
  const savΔ  = (savP != null && savC != null) ? (savC - savP) : null;
  const row = (label, p, c, deltaPct, unit) => `<tr>
    <td class="l">${label}</td>
    <td>${p == null ? '—' : fmtC(p, true)}</td>
    <td>${c == null ? '—' : fmtC(c, true)}</td>
    <td>${_pctChip(deltaPct, { unit: unit || '%', flatThreshold: unit === 'pp' ? 1 : 2 })}</td>
  </tr>`;
  const rowPct = (label, p, c, deltaPp) => `<tr>
    <td class="l">${label}</td>
    <td>${p == null ? '—' : p + '%'}</td>
    <td>${c == null ? '—' : c + '%'}</td>
    <td>${_pctChip(deltaPp, { unit: 'pp', flatThreshold: 1 })}</td>
  </tr>`;
  return `<table class="cmp-table">
    <thead><tr><th class="l"></th><th>${esc(priorLabel)}</th><th>${esc(currLabel)}</th><th>Δ</th></tr></thead>
    <tbody>
      ${row('Доходы',  prior.income_rub,  curr.income_rub,  incΔ)}
      ${row('Расходы', prior.expense_rub, curr.expense_rub, expΔ)}
      ${row('Сальдо',  netP, netC, netΔ)}
      ${rowPct('Норма сбережений', savP, savC, savΔ)}
    </tbody>
  </table>`;
}

function _moversList(movers) {
  // movers: [{tag, current_rub, prior_rub, delta_rub, delta_pct}], sorted by abs(delta)
  if (!movers || movers.length === 0) {
    return `<div class="mv-grid"><div class="mv-col"><div class="mv-empty">Нет данных за прошлый период</div></div><div class="mv-col"><div class="mv-empty">—</div></div></div>`;
  }
  const ups   = movers.filter(m => m.delta_rub > 0).slice(0, 5);
  const downs = movers.filter(m => m.delta_rub < 0).slice(0, 5);
  const fmtDelta = (d) => (d > 0 ? '+' : '−') + fmtC(Math.abs(d), true);
  const renderRow = (m) => {
    const pctHtml = m.delta_pct == null
      ? `<span class="mv-pct new">новая</span>`
      : `<span class="mv-pct ${m.delta_pct >= 0 ? 'pos' : 'neg'}">${m.delta_pct > 0 ? '+' : ''}${m.delta_pct}%</span>`;
    return `<div class="mv-row">
      <span class="mv-tag">#${esc(m.tag)}</span>
      <span class="mv-amt">${fmtDelta(m.delta_rub)}</span>
      ${pctHtml}
    </div>`;
  };
  return `<div class="mv-grid">
    <div class="mv-col">
      <div class="mv-col-head"><span style="color:var(--red)">↑</span> Выросли</div>
      ${ups.length ? ups.map(renderRow).join('') : '<div class="mv-empty">Нет роста</div>'}
    </div>
    <div class="mv-col">
      <div class="mv-col-head"><span style="color:var(--green)">↓</span> Сократились</div>
      ${downs.length ? downs.map(renderRow).join('') : '<div class="mv-empty">Нет сокращений</div>'}
    </div>
  </div>`;
}

async function loadMovers(currFrom, currTo, prevFrom, prevTo) {
  if (!HOUSEHOLD_ID) return null;
  const url = new URL('/finance/category_movers', location.origin);
  url.searchParams.set('household_id', HOUSEHOLD_ID);
  url.searchParams.set('from', currFrom);
  url.searchParams.set('to', currTo);
  url.searchParams.set('prev_from', prevFrom);
  url.searchParams.set('prev_to', prevTo);
  try {
    const r = await fetch(url);
    if (!r.ok) return { _error: `HTTP ${r.status}` };
    return await r.json();
  } catch (e) { return { _error: e.message }; }
}
```

- [x] **Step 2: Commit**

```bash
git add app/dashboard/templates/monthly_report.html
git commit -m "feat(web): shared QoQ/YoY JS helpers — period bounds, compare table, movers list

_qPrevRange / _yPrevRange compute prior bounds. _compareTable renders the
4-row Доходы/Расходы/Сальдо/Норма comparison (handles missing prior).
_moversList renders ↑/↓ two-column with 'новая' badge for new tags.
loadMovers fetches the new /finance/category_movers endpoint."
```

---

## Task 5: Frontend — rewrite `renderQuarterly`

**Files:**
- Modify: `app/dashboard/templates/monthly_report.html` — replace existing `renderQuarterly` function (currently around line ~1200–1246)

- [x] **Step 1: Replace `renderQuarterly`**

Find the existing `async function renderQuarterly() { ... }` block and replace its entire body (keep the `async function renderQuarterly()` signature) with:

```javascript
async function renderQuarterly() {
  const { curr, prior } = _qPrevRange(_REPORT_YEAR, _REPORT_MONTH);
  document.getElementById('q-hero-amount').textContent = '…';
  document.getElementById('q-hero-meta').innerHTML = '';
  document.getElementById('q-compare').innerHTML = '<div style="padding:14px 16px;color:var(--muted);font-size:13px">Загрузка…</div>';
  document.getElementById('q-movers').innerHTML = '';
  document.getElementById('q-body').innerHTML = '';

  // Parallel fetch: two separate loadRange calls (prior Q, current Q) so we
  // don't depend on the RPC including a year column — each call returns 3
  // months within a single year, identifiable by m.mo alone.
  const [priorMonths, currMonths, movers] = await Promise.all([
    loadRange(prior.from, prior.to),
    loadRange(curr.from,  curr.to),
    loadMovers(curr.from, curr.to, prior.from, prior.to),
  ]);

  const sumIncExp = (rows) => rows.reduce((acc, m) => {
    acc.inc += Number(m.actual_income_rub  || 0);
    acc.exp += Number(m.actual_expense_rub || 0);
    return acc;
  }, { inc: 0, exp: 0 });
  const p = sumIncExp(priorMonths);
  const c = sumIncExp(currMonths);
  let pInc = p.inc, pExp = p.exp, cInc = c.inc, cExp = c.exp;
  const [cfy, cfm] = curr.from.split('-').map(Number);
  const cNet = cInc - cExp;
  const pNet = pInc - pExp;
  const cSav = cInc > 0 ? Math.round(cNet / cInc * 100) : null;

  // Hero
  document.getElementById('q-hero-label').textContent = `Сальдо квартала · ${curr.label}`;
  document.getElementById('q-hero-amount').innerHTML = (cNet >= 0 ? '+' : '') + fmtC(cNet) + ' ' + _pctChip(_safePct(cNet, pNet));
  const metaTxt = `доход ${fmtC(cInc, true)} · расход ${fmtC(cExp, true)}` +
                  (cSav != null ? ` · норма ${cSav}%` : '');
  document.getElementById('q-hero-meta').innerHTML = `<span class="hero-meta-muted">${metaTxt}</span>`;

  // Compare
  document.getElementById('q-compare').innerHTML = _compareTable({
    priorLabel: prior.label,
    currLabel:  curr.label,
    prior: { income_rub: pInc, expense_rub: pExp },
    curr:  { income_rub: cInc, expense_rub: cExp },
  });

  // Movers
  if (!movers || movers._error) {
    document.getElementById('q-movers').innerHTML = `<div class="mv-empty" style="padding:14px 16px">Не удалось загрузить движения (${movers ? movers._error : 'нет данных'})</div>`;
  } else {
    document.getElementById('q-movers').innerHTML = _moversList(movers.movers);
  }

  // Per-month rows (current quarter only — 3 rows + total)
  const qStart = cfm;
  const currByMo = new Map(currMonths.map(m => [m.mo, m]));
  const rows = [];
  for (let mm = qStart; mm <= qStart + 2; mm++) {
    const r = currByMo.get(mm);
    const inc = r ? Number(r.actual_income_rub  || 0) : 0;
    const exp = r ? Number(r.actual_expense_rub || 0) : 0;
    const net = inc - exp;
    const sav = inc > 0 ? Math.round(net / inc * 100) : null;
    const isCurr = (mm === _REPORT_MONTH && cfy === _REPORT_YEAR);
    rows.push(`<tr style="${isCurr ? 'background:#1c1c22' : ''}">
      <td>${MONTHS_FULL[mm]}${isCurr ? ' <span style="font-size:9px;background:#1e3a5f;color:#93c5fd;border:1px solid #1d4ed8;border-radius:3px;padding:1px 5px;margin-left:4px">текущий</span>' : ''}</td>
      <td class="r mono" style="color:${inc ? 'var(--green)' : 'var(--subtle)'}">${inc ? '+' + fmtC(inc, true) : '—'}</td>
      <td class="r mono" style="color:${exp ? 'var(--red)' : 'var(--subtle)'}">${exp ? '−' + fmtC(exp, true) : '—'}</td>
      <td class="r mono" style="color:${net >= 0 ? 'var(--green)' : 'var(--red)'}">${(net >= 0 ? '+' : '') + fmtC(net, true)}</td>
      <td class="r mono">${sav == null ? '—' : sav + '%'}</td>
    </tr>`);
  }
  rows.push(`<tr style="border-top:2px solid var(--border)">
    <td style="font-weight:600">Итого ${curr.label}</td>
    <td class="r mono" style="color:var(--green)">+${fmtC(cInc, true)}</td>
    <td class="r mono" style="color:var(--red)">−${fmtC(cExp, true)}</td>
    <td class="r mono" style="color:${cNet >= 0 ? 'var(--green)' : 'var(--red)'}">${(cNet >= 0 ? '+' : '') + fmtC(cNet, true)}</td>
    <td class="r mono">${cSav == null ? '—' : cSav + '%'}</td>
  </tr>`);
  document.getElementById('q-body').innerHTML = rows.join('');
}
```

- [x] **Step 2: Commit**

```bash
git add app/dashboard/templates/monthly_report.html
git commit -m "feat(web): renderQuarterly rewritten with QoQ hero/compare/movers/months

Parallel fetch /report/range (6mo: prior Q + current Q) and
/category_movers. Hero gets delta chip vs prior Q. Per-month rows
keep the existing 'текущий' badge for the current month."
```

---

## Task 6: Frontend — rewrite `renderAnnual`

**Files:**
- Modify: `app/dashboard/templates/monthly_report.html` — replace existing `renderAnnual` function (currently around line ~1311–1347)

- [x] **Step 1: Replace `renderAnnual`**

Find the existing `async function renderAnnual() { ... }` block and replace its entire body (keep signature) with:

```javascript
async function renderAnnual() {
  const { curr, prior } = _yPrevRange(_REPORT_YEAR);
  document.getElementById('a-hero-amount').textContent = '…';
  document.getElementById('a-hero-meta').innerHTML = '';
  document.getElementById('a-compare').innerHTML = '<div style="padding:14px 16px;color:var(--muted);font-size:13px">Загрузка…</div>';
  document.getElementById('a-movers').innerHTML = '';
  document.getElementById('a-summary').innerHTML = '';

  // Two separate loadRange calls so we don't depend on the RPC including a
  // year column — each call returns 12 months within a single year.
  const [priorRows, currRows, movers] = await Promise.all([
    loadRange(prior.from, prior.to),
    loadRange(curr.from,  curr.to),
    loadMovers(curr.from, curr.to, prior.from, prior.to),
  ]);

  let pInc = 0, pExp = 0, cInc = 0, cExp = 0;
  const currMonths = [];
  for (const m of priorRows) {
    pInc += Number(m.actual_income_rub  || 0);
    pExp += Number(m.actual_expense_rub || 0);
  }
  for (const m of currRows) {
    const inc = Number(m.actual_income_rub  || 0);
    const exp = Number(m.actual_expense_rub || 0);
    cInc += inc; cExp += exp;
    currMonths.push({ mo: m.mo, inc, exp });
  }
  const cNet = cInc - cExp;
  const pNet = pInc - pExp;
  const cSav = cInc > 0 ? Math.round(cNet / cInc * 100) : null;

  // Hero
  document.getElementById('a-hero-label').textContent = `Сальдо года · ${curr.label}`;
  document.getElementById('a-hero-amount').innerHTML = (cNet >= 0 ? '+' : '') + fmtC(cNet) + ' ' + _pctChip(_safePct(cNet, pNet));
  const metaTxt = `доход ${fmtC(cInc, true)} · расход ${fmtC(cExp, true)}` + (cSav != null ? ` · норма ${cSav}%` : '');
  document.getElementById('a-hero-meta').innerHTML = `<span class="hero-meta-muted">${metaTxt}</span>`;

  // Compare
  document.getElementById('a-compare').innerHTML = _compareTable({
    priorLabel: prior.label,
    currLabel:  curr.label,
    prior: { income_rub: pInc, expense_rub: pExp },
    curr:  { income_rub: cInc, expense_rub: cExp },
  });

  // Movers
  if (!movers || movers._error) {
    document.getElementById('a-movers').innerHTML = `<div class="mv-empty" style="padding:14px 16px">Не удалось загрузить движения (${movers ? movers._error : 'нет данных'})</div>`;
  } else {
    document.getElementById('a-movers').innerHTML = _moversList(movers.movers);
  }

  // Insights inset (preserved from previous Annual narrative)
  let bestMonth = null, worstMonth = null;
  currMonths.forEach(m => {
    const net = m.inc - m.exp;
    if (!bestMonth || net > bestMonth.net) bestMonth = { mo: m.mo, net };
    if (!worstMonth || m.exp > worstMonth.exp) worstMonth = { mo: m.mo, exp: m.exp };
  });
  let summary = '';
  if (currMonths.length === 0) {
    summary = '<div class="placeholder">Нет данных за этот год</div>';
  } else {
    summary = `<ul style="list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:8px;font-size:13px">
      ${bestMonth ? `<li>📈 Лучший месяц по сальдо: <b>${MONTHS_FULL[bestMonth.mo]}</b> (${fmtC(bestMonth.net, true)})</li>` : ''}
      ${worstMonth ? `<li>💸 Самый расходный месяц: <b>${MONTHS_FULL[worstMonth.mo]}</b> (${fmtC(worstMonth.exp, true)})</li>` : ''}
      <li>📊 Месяцев с данными: <b>${currMonths.length}</b> из 12</li>
      <li>💰 Средний доход в месяц: <b>${fmtC(currMonths.length ? cInc / currMonths.length : 0, true)}</b></li>
      <li>🧾 Средний расход в месяц: <b>${fmtC(currMonths.length ? cExp / currMonths.length : 0, true)}</b></li>
    </ul>`;
  }
  document.getElementById('a-summary').innerHTML = summary;
}
```

- [x] **Step 2: Commit**

```bash
git add app/dashboard/templates/monthly_report.html
git commit -m "feat(web): renderAnnual rewritten as YoY view

Hero shows year sal'do + YoY chip. Compare/movers blocks mirror the
Quarterly tab. Insights inset (best/worst month, monthly avg) is
preserved here and dropped from the Yearly tab tail."
```

---

## Task 7: Frontend — tab state persistence (URL `?tab=`)

**Files:**
- Modify: `app/dashboard/templates/monthly_report.html` — three small JS edits

- [x] **Step 1: Modify `switchTab` to update the URL**

Find:

```javascript
function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.h-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-view').forEach(v => v.classList.toggle('active', v.id === `tab-${tab}`));
  renderActiveTab();
}
```

Replace with:

```javascript
function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.h-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-view').forEach(v => v.classList.toggle('active', v.id === `tab-${tab}`));
  // Persist tab in URL so reloads / period nav land on the same tab.
  const url = new URL(location.href);
  if (tab === 'monthly') url.searchParams.delete('tab');
  else url.searchParams.set('tab', tab);
  history.replaceState(null, '', url.toString());
  renderActiveTab();
}
```

- [x] **Step 2: Modify `navPeriod` to carry the tab**

Find:

```javascript
function navPeriod(delta) {
  let y = _REPORT_YEAR, m = _REPORT_MONTH;
  if (activeTab === 'monthly') {
    m += delta;
  } else if (activeTab === 'quarterly') {
    m += delta * 3;
  } else {
    // year / annual
    const params = new URLSearchParams(location.search);
    params.set('month', `${y+delta}-01`);
    location.search = params.toString();
    return;
  }
  while (m < 1)  { m += 12; y--; }
  while (m > 12) { m -= 12; y++; }
  const params = new URLSearchParams(location.search);
  params.set('month', `${y}-${String(m).padStart(2,'0')}`);
  location.search = params.toString();
}
```

Replace with:

```javascript
function navPeriod(delta) {
  let y = _REPORT_YEAR, m = _REPORT_MONTH;
  const params = new URLSearchParams(location.search);
  // Carry active tab unless we're on the default (monthly).
  if (activeTab && activeTab !== 'monthly') params.set('tab', activeTab);

  if (activeTab === 'monthly' || activeTab === 'cashflow') {
    m += delta;
  } else if (activeTab === 'quarterly') {
    m += delta * 3;
  } else {
    // year / annual: shift by full year, anchor to Jan
    params.set('month', `${y + delta}-01`);
    location.search = params.toString();
    return;
  }
  while (m < 1)  { m += 12; y--; }
  while (m > 12) { m -= 12; y++; }
  params.set('month', `${y}-${String(m).padStart(2,'0')}`);
  location.search = params.toString();
}
```

- [x] **Step 3: Read the tab from the URL on boot**

Find the very end of the `<script>` block where the page boots (look for `renderActiveTab()` being called without `switchTab`, or the IIFE that calls `renderMonthly`/initial render). Right before that initial render runs, insert:

```javascript
// Initial tab from URL (?tab=) — default monthly.
const _initialTab = (new URLSearchParams(location.search)).get('tab');
if (_initialTab && document.getElementById(`tab-${_initialTab}`)) {
  // Mirror what switchTab does, but without rewriting the URL (already there).
  activeTab = _initialTab;
  document.querySelectorAll('.h-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === _initialTab));
  document.querySelectorAll('.tab-view').forEach(v => v.classList.toggle('active', v.id === `tab-${_initialTab}`));
}
```

This must run BEFORE the page's first `renderActiveTab()` call. If the existing boot calls `renderHero()`/`renderAccounts()`/etc. directly (not `renderActiveTab`), follow it with `renderActiveTab()` if `_initialTab` was applied — but only if the tab differs from `monthly` (the inline boot already renders monthly).

Search for the trailing boot lines to confirm placement. Pattern in the current file:

```javascript
// (boot block — currently looks roughly like)
renderHero();
renderAccounts();
renderStats();
renderAlerts();
renderIncome();
renderCashflowChart();
renderTagAnalytics();
renderLedger();
updatePeriodLabel();
```

Insert the `_initialTab` block ABOVE these calls. Then, AFTER all the monthly-render calls, append:

```javascript
if (_initialTab && _initialTab !== 'monthly' && document.getElementById(`tab-${_initialTab}`)) {
  renderActiveTab();
}
```

- [x] **Step 4: Commit**

```bash
git add app/dashboard/templates/monthly_report.html
git commit -m "feat(web): persist active tab in URL (?tab=)

switchTab now updates ?tab= via history.replaceState; navPeriod carries
the tab into the next URL; boot reads ?tab= and re-renders the tab if
non-monthly. Fixes the quarter switcher dumping users back to Monthly."
```

---

## Task 8: Push, deploy, verify on Vercel

**Files:** none — this is verification.

- [ ] **Step 1: Push the branch**

Run: `git push git@github.com:miordanus/hastlefam.git feat/dashboard-tabs-qoq-yoy:feat/dashboard-tabs-qoq-yoy`

Expected: branch pushed, GitHub URL printed for opening a PR.

- [ ] **Step 2: Open the PR**

Run:

```bash
gh pr create --base main --head feat/dashboard-tabs-qoq-yoy \
  --title "feat(web): QoQ + YoY tab redesign + /finance/category_movers" \
  --body "$(cat <<'EOF'
## Summary
Restructures the Quarterly and Annual tabs from summary-only into comparison-first layouts (hero / compare / movers / per-period detail). Fixes the quarter switcher: tab state now persists in `?tab=` so `‹/›` doesn't dump you back on Monthly. Adds a new `/finance/category_movers` REST-mode endpoint for per-tag expense deltas across two periods.

Spec: `docs/superpowers/specs/2026-05-24-dashboard-tabs-redesign.md`.

## Test plan
- [ ] Vercel deploy succeeds
- [ ] Open `/finance/report?household_id=...`, switch to Квартал; click ‹/›: stays on Квартал, period changes, data loads
- [ ] Quarterly hero shows current Q net + ▲/▼ vs prior Q
- [ ] Compare table renders all four rows; Δ chips colored
- [ ] Movers ↑/↓ render with top expenses; "новая" badge appears if a new tag exists
- [ ] Per-month rows highlight the current month
- [ ] Same checks for Годовой отчёт (YoY)
- [ ] Yearly tab still works (unchanged), insights inset still rendered there? — confirm we did NOT remove it accidentally
- [ ] `GET /finance/category_movers?household_id=...&from=2026-04&to=2026-06&prev_from=2026-01&prev_to=2026-03` returns 200 + expected shape
- [ ] Without REST creds: 503 (manual test in dev env, not Vercel)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

- [ ] **Step 3: Wait for Vercel preview and verify**

Wait for the Vercel preview build (Linked from PR). Open the preview URL with `?household_id=<existing-hid>`.

Walk through the test plan checklist in the PR body. Note any visual issues; fix in follow-up commits on the same branch.

- [ ] **Step 4: Final commit (if any fixes)**

If verification surfaced anything, commit a fix:

```bash
git add <files>
git commit -m "fix(web): <specific issue from verification>"
git push git@github.com:miordanus/hastlefam.git feat/dashboard-tabs-qoq-yoy:feat/dashboard-tabs-qoq-yoy
```

---

## Self-review (planner's checklist)

- [x] **Spec coverage:**
  - Tab persistence — Task 7
  - Quarterly hero/compare/movers/months — Task 5 (using Task 3 HTML + Task 4 helpers)
  - Annual hero/compare/movers/insights — Task 6 (using Task 3 HTML + Task 4 helpers)
  - Backend `/finance/category_movers` — Tasks 1, 2
  - Edge cases (no prior data, new category, disappeared category, 503) — handled in Task 4 helpers + Task 1 service code
  - Vercel verification — Task 8
- [x] **No placeholders:** every step has actual code or actual commands.
- [x] **Type consistency:** Backend method returns `{current, prior, movers}`; frontend `loadMovers` consumes `movers.movers`; helpers use `delta_rub` / `delta_pct` consistently. `MONTHS_FULL` global is reused. `fmtC(rub, compact)`, `esc()` are existing globals used as-is.

---

## Risk notes (for the implementer)

- **`/finance/report/range` response shape.** Task 5/6 read only `m.mo`, `m.actual_income_rub`, `m.actual_expense_rub`. We do NOT depend on `m.y` because we issue two separate `loadRange` calls (prior + current) — each return only months in a single year. If the RPC returns extra columns it doesn't hurt; if it's missing a year column it doesn't matter.
- **`_qPrevRange` Q-1 of Q1 case.** Q1 2026 → prior is Q4 2025. The arithmetic crosses year boundaries — covered by `norm()`, but worth eyeballing the prior label in the UI. The `Math.ceil(prevQStart<=0?(prevQStart+12)/3:prevQStart/3)` is fragile; if the prior label reads wrong, simplify to: compute `qNum = Math.ceil(prev.m/3)` from the normalized `prev.m`.
- **Tag with special chars** in `primary_tag`. We HTML-escape via `esc()` in `_moversList`. Backend stores raw — no double-escape needed.
- **FX fallback** in `_to_rub`: defaults to 1.0 if rate missing. For unusual currencies this skews totals. Consistent with existing methods.
