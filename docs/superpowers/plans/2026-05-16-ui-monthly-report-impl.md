# UI Monthly Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the Monthly Report UI — add tag analytics section to the prototype, build the `/finance/report` backend endpoint, and wire the HTML template to real data replacing mock.

**Architecture:** Four independent tasks in dependency order: (1) tag analytics UI added to prototype with mock data; (2) `FinanceService.monthly_report()` method returning real transaction + account + snapshot data; (3) FastAPI route serving the HTML template with injected JSON; (4) template wiring — replace JS `MOCK DATA` block with Jinja2-injected `DATA`. Running balance is computed client-side from sorted transactions + starting snapshot (no DB field needed).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Jinja2, vanilla JS + Chart.js, pytest + SQLite in-memory.

---

## Files Changed

| File | What changes |
|---|---|
| `app/dashboard/templates/monthly_report.html` | Add tag analytics section; wire `DATA` from Jinja2 |
| `app/application/services/finance_service.py` | Add `monthly_report()` method |
| `app/api/routers/finance.py` | Add `GET /finance/report` HTML route + `GET /finance/report/data` JSON route |
| `tests/test_finance_report.py` | New — tests for `monthly_report()` and the JSON endpoint |

---

## Task 1: Tag Analytics UI (prototype, mock data)

**Files:**
- Modify: `app/dashboard/templates/monthly_report.html`

The tag analytics section goes inside `#tab-monthly`, after the ledger div and before the `<footer>`. It shows a table: tag | total spent | % of actual expenses | 31-day mini sparkline (CSS bars, one per calendar day).

- [ ] **Step 1: Add tag analytics section HTML**

In `app/dashboard/templates/monthly_report.html`, find the closing `</div><!-- /tab-monthly -->` comment and insert before it:

```html
    <!-- tag analytics -->
    <div>
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">
        <span style="font-size:12px;font-weight:600;color:#a1a1aa;text-transform:uppercase;letter-spacing:.06em;">По тегам</span>
        <span id="tag-period-label" style="font-size:12px;color:#52525b;"></span>
      </div>
      <div class="ledger-wrap">
        <div style="overflow-x:auto;">
          <table class="ledger-table" id="tag-table">
            <thead>
              <tr>
                <th style="text-align:left;">Тег</th>
                <th style="text-align:right;">Сумма</th>
                <th style="text-align:right;">% расходов</th>
                <th style="text-align:left;padding-left:24px;">Тренд (май)</th>
              </tr>
            </thead>
            <tbody id="tag-table-body"></tbody>
          </table>
        </div>
      </div>
    </div>
```

- [ ] **Step 2: Add sparkline CSS**

In the `<style>` block, add:

```css
.sparkline { display:inline-flex; align-items:flex-end; gap:1px; height:20px; }
.sparkline span { width:6px; border-radius:1px 1px 0 0; min-height:2px; display:inline-block; }
```

- [ ] **Step 3: Add `renderTagAnalytics()` function in JS**

Add this function before the `// ─── INIT` comment:

```js
// ══════════════════════════════════════════════════════════════════════════════
// TAG ANALYTICS
// ══════════════════════════════════════════════════════════════════════════════
function renderTagAnalytics() {
  // Build per-tag totals and per-day amounts from actual, non-planned expense txs
  const expenseTxs = LEDGER.filter(t => !t.is_planned && t.direction === 'expense');
  const totalExpRub = expenseTxs.reduce((s, t) => s + t.rubAmount, 0);

  // {tag: {total: number, days: {[day: string]: number}}}
  const tagMap = {};
  expenseTxs.forEach(t => {
    const tag = t.primary_tag || '(без тега)';
    if (!tagMap[tag]) tagMap[tag] = { total: 0, days: {} };
    tagMap[tag].total += t.rubAmount;
    const day = t.occurred_at.slice(8, 10); // "01".."31"
    tagMap[tag].days[day] = (tagMap[tag].days[day] || 0) + t.rubAmount;
  });

  const tags = Object.entries(tagMap).sort((a, b) => b[1].total - a[1].total);

  document.getElementById('tag-period-label').textContent = `${tags.length} тегов · ${fmtC(totalExpRub)} расходов`;

  const body = document.getElementById('tag-table-body');
  if (!tags.length) { body.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#52525b;padding:32px;">Нет данных</td></tr>'; return; }

  const maxDay = Math.max(...tags.map(([, d]) => Math.max(...Object.values(d.days), 1)));

  body.innerHTML = tags.map(([tag, data]) => {
    const pct = totalExpRub > 0 ? ((data.total / totalExpRub) * 100).toFixed(1) : '0.0';
    // 31 bars, one per calendar day
    const bars = Array.from({ length: 31 }, (_, i) => {
      const day = String(i + 1).padStart(2, '0');
      const val = data.days[day] || 0;
      const h = val ? Math.max(3, Math.round((val / maxDay) * 20)) : 2;
      const alpha = val ? 0.7 : 0.12;
      return `<span style="height:${h}px;background:rgba(248,113,113,${alpha});"></span>`;
    }).join('');
    return `<tr class="ledger-row">
      <td><span class="tag-pill">#${tag}</span></td>
      <td class="mono" style="text-align:right;color:#f87171;">−${fmtC(data.total)}</td>
      <td class="mono" style="text-align:right;color:#71717a;">${pct}%</td>
      <td style="padding-left:24px;"><div class="sparkline">${bars}</div></td>
    </tr>`;
  }).join('');
}
```

- [ ] **Step 4: Call `renderTagAnalytics()` from init and from `renderActiveTab`**

In the `// ─── INIT` block, add:
```js
renderTagAnalytics();
```

In `renderActiveTab()`, extend the monthly branch:
```js
if(activeTab==='monthly'){ renderSummary(); renderLedger(); renderCashflowChart(); renderTagAnalytics(); }
```

- [ ] **Step 5: Verify visually**

Open http://localhost:3333/monthly_report.html — scroll past the ledger on the Месяц tab. Should see a "По тегам" table with tag rows, % column, and mini bar sparklines. Switch ₽/$ — amounts convert. No automated test (pure UI).

- [ ] **Step 6: Commit**

```bash
git add app/dashboard/templates/monthly_report.html
git commit -m "feat(ui): add tag analytics section with sparklines to monthly report"
```

---

## Task 2: `FinanceService.monthly_report()` backend method

**Files:**
- Modify: `app/application/services/finance_service.py`
- Create: `tests/test_finance_report.py`

Returns a dict with: accounts, per-account balance snapshots, all transactions for the month (planned + actual, excluding internal transfers and exchanges), and tag summary for actual expenses.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_finance_report.py`:

```python
"""Tests for FinanceService.monthly_report()."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Account, BalanceSnapshot, Transaction
from tests.conftest import HOUSEHOLD_ID


def _make_tx(db, *, occurred_at, direction, amount, currency=Currency.RUB,
              is_planned=False, is_internal_transfer=False, primary_tag=None,
              account_id=None):
    tx = Transaction(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        direction=direction,
        amount=amount,
        currency=currency,
        occurred_at=occurred_at,
        merchant_raw="test",
        source="test",
        parse_status="ok",
        is_planned=is_planned,
        is_internal_transfer=is_internal_transfer,
        is_skipped=False,
        primary_tag=primary_tag,
        extra_tags=[],
        account_id=account_id,
    )
    db.add(tx)
    return tx


def _make_account(db, name="Тест", currency=Currency.RUB):
    acc = Account(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        name=name,
        currency=currency,
        is_shared=True,
        is_active=True,
    )
    db.add(acc)
    return acc


def _make_snapshot(db, account_id, actual_balance, created_at):
    snap = BalanceSnapshot(
        id=uuid.uuid4(),
        account_id=account_id,
        household_id=HOUSEHOLD_ID,
        actual_balance=actual_balance,
        created_at=created_at,
    )
    db.add(snap)
    return snap


def test_monthly_report_returns_accounts(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.commit()
    svc = FinanceService(seeded_db)
    result = svc.monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    account_ids = [a["id"] for a in result["accounts"]]
    assert str(acc.id) in account_ids


def test_monthly_report_transactions_include_planned(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.flush()
    _make_tx(seeded_db, occurred_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
             direction=TransactionDirection.EXPENSE, amount=1000, is_planned=True,
             account_id=acc.id)
    _make_tx(seeded_db, occurred_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
             direction=TransactionDirection.EXPENSE, amount=500, is_planned=False,
             account_id=acc.id)
    seeded_db.commit()
    result = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    assert len(result["transactions"]) == 2


def test_monthly_report_excludes_internal_transfers(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.flush()
    _make_tx(seeded_db, occurred_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
             direction=TransactionDirection.EXPENSE, amount=500,
             is_internal_transfer=True, account_id=acc.id)
    seeded_db.commit()
    result = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    assert result["transactions"] == []


def test_monthly_report_excludes_exchange_direction(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.flush()
    _make_tx(seeded_db, occurred_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
             direction=TransactionDirection.EXCHANGE, amount=500, account_id=acc.id)
    seeded_db.commit()
    result = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    assert result["transactions"] == []


def test_monthly_report_excludes_other_months(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.flush()
    _make_tx(seeded_db, occurred_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
             direction=TransactionDirection.EXPENSE, amount=999, account_id=acc.id)
    seeded_db.commit()
    result = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    assert result["transactions"] == []


def test_monthly_report_snapshot_latest_before_month(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.flush()
    _make_snapshot(seeded_db, acc.id, actual_balance=50000,
                   created_at=datetime(2026, 4, 28, tzinfo=timezone.utc))
    _make_snapshot(seeded_db, acc.id, actual_balance=60000,
                   created_at=datetime(2026, 5, 15, tzinfo=timezone.utc))  # inside month — excluded
    seeded_db.commit()
    result = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    snap = result["snapshots"].get(str(acc.id))
    assert snap is not None
    assert snap["actual_balance"] == 50000.0


def test_monthly_report_tag_summary_actual_expenses_only(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.flush()
    _make_tx(seeded_db, occurred_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
             direction=TransactionDirection.EXPENSE, amount=5000,
             primary_tag="продукты", account_id=acc.id)
    _make_tx(seeded_db, occurred_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
             direction=TransactionDirection.EXPENSE, amount=3000,
             primary_tag="продукты", is_planned=True, account_id=acc.id)  # planned — excluded from tag summary
    seeded_db.commit()
    result = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    tag = next((t for t in result["tag_summary"] if t["tag"] == "продукты"), None)
    assert tag is not None
    assert tag["total_rub"] == 5000.0  # planned not counted
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_finance_report.py -v
```

Expected: `AttributeError: 'FinanceService' object has no attribute 'monthly_report'`

- [ ] **Step 3: Implement `monthly_report()` in `FinanceService`**

In `app/application/services/finance_service.py`, after the `month_summary` method (around line 90), add:

```python
    def monthly_report(self, household_id: str, year: int, month: int) -> dict[str, Any]:
        """Return all data needed by the monthly report UI.

        Includes both planned and actual transactions (ЗАКОН filters applied).
        Running balance is computed client-side from this data + snapshots.
        """
        import calendar as _cal

        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id
        month_start = date(year, month, 1)
        month_end_day = _cal.monthrange(year, month)[1]
        start_dt = datetime(year, month, 1, tzinfo=timezone.utc)
        end_dt = datetime(year, month, month_end_day, 23, 59, 59, tzinfo=timezone.utc)

        # Accounts
        accounts = (
            self.db.query(Account)
            .filter(Account.household_id == hid, Account.is_active.is_(True))
            .all()
        )

        # All transactions for the month (planned + actual) — ЗАКОН filters
        txs = (
            self.db.query(Transaction)
            .filter(
                Transaction.household_id == hid,
                Transaction.occurred_at >= start_dt,
                Transaction.occurred_at <= end_dt,
                Transaction.is_internal_transfer.is_(False),
                Transaction.is_skipped.is_(False),
                Transaction.direction != TransactionDirection.EXCHANGE,
            )
            .order_by(Transaction.occurred_at.asc())
            .all()
        )

        # Latest BalanceSnapshot per account strictly before month start
        snapshots: dict[str, dict | None] = {}
        for acc in accounts:
            snap = (
                self.db.query(BalanceSnapshot)
                .filter(
                    BalanceSnapshot.account_id == acc.id,
                    BalanceSnapshot.created_at < start_dt,
                )
                .order_by(BalanceSnapshot.created_at.desc())
                .first()
            )
            snapshots[str(acc.id)] = (
                {"actual_balance": float(snap.actual_balance)} if snap else None
            )

        # Tag summary — actual expenses only (ЗАКОН: is_planned=False)
        tag_map: dict[str, float] = {}
        for tx in txs:
            if tx.is_planned or tx.direction != TransactionDirection.EXPENSE:
                continue
            tag = tx.primary_tag or "(без тега)"
            tag_map[tag] = tag_map.get(tag, 0.0) + float(tx.amount)

        tag_summary = [
            {"tag": t, "total_rub": v}
            for t, v in sorted(tag_map.items(), key=lambda x: -x[1])
        ]

        return {
            "year": year,
            "month": month,
            "accounts": [
                {"id": str(a.id), "name": a.name, "currency": a.currency.value}
                for a in accounts
            ],
            "snapshots": snapshots,
            "transactions": [
                {
                    "id": str(tx.id),
                    "occurred_at": tx.occurred_at.strftime("%Y-%m-%d"),
                    "direction": tx.direction.value,
                    "amount": float(tx.amount),
                    "currency": tx.currency.value if tx.currency else "rub",
                    "merchant_raw": tx.merchant_raw or "",
                    "primary_tag": tx.primary_tag,
                    "account_id": str(tx.account_id) if tx.account_id else None,
                    "is_planned": tx.is_planned,
                    "is_internal_transfer": tx.is_internal_transfer,
                    "status": _derive_status(tx),
                }
                for tx in txs
            ],
            "tag_summary": tag_summary,
        }
```

Add the helper `_derive_status` as a module-level function at the bottom of `finance_service.py` (after all class methods):

```python
def _derive_status(tx: Transaction) -> str:
    """Derive UI status from transaction state.

    actual    — normal recorded transaction
    planned   — future planned entry (is_planned=True, not yet overdue)
    overdue   — planned entry whose date has passed with no linked actual
    matched   — actual transaction linked to a planned one
    mismatch  — actual differs from planned amount by >5%
    unplanned — user explicitly marked with [сюрприз]
    """
    from datetime import date, timezone
    today = date.today()
    occurred = tx.occurred_at.date() if hasattr(tx.occurred_at, "date") else tx.occurred_at

    if tx.is_planned:
        if occurred <= today:
            return "overdue"
        return "planned"

    # Check merchant_raw for explicit surprise marker
    raw = (tx.merchant_raw or "").lower()
    if "[сюрприз]" in raw or "[surprise]" in raw:
        return "unplanned"

    return "actual"
```

Note: matched/mismatch require a PlannedPayment.linked_transaction_id lookup — not implemented yet, returns "actual" for now. Add later when reconciliation UI is built.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_finance_report.py -v
```

Expected: all 7 pass.

- [ ] **Step 5: Run full suite to check for regressions**

```bash
pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/application/services/finance_service.py tests/test_finance_report.py
git commit -m "feat(finance): add monthly_report() service method with tag summary"
```

---

## Task 3: FastAPI route `/finance/report`

**Files:**
- Modify: `app/api/routers/finance.py`
- Modify: `tests/test_finance_report.py` (add route tests)

Two routes: one serves the HTML template (browser), one serves the JSON data (API / future AJAX).

- [ ] **Step 1: Add route tests**

Append to `tests/test_finance_report.py`:

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_report_data_endpoint_requires_household_id():
    resp = client.get("/finance/report/data")
    assert resp.status_code == 422  # missing required query param


def test_report_data_endpoint_returns_json(seeded_db, monkeypatch):
    import app.api.routers.finance as fin_router
    from app.application.services.finance_service import FinanceService

    def fake_report(self, household_id, year, month):
        return {"accounts": [], "snapshots": {}, "transactions": [], "tag_summary": [],
                "year": year, "month": month}

    monkeypatch.setattr(FinanceService, "monthly_report", fake_report)
    resp = client.get("/finance/report/data?household_id=00000000-0000-0000-0000-000000000001&month=2026-05")
    assert resp.status_code == 200
    data = resp.json()
    assert "transactions" in data
    assert data["year"] == 2026
    assert data["month"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_finance_report.py::test_report_data_endpoint_requires_household_id -v
```

Expected: `FAILED` — route doesn't exist yet.

- [ ] **Step 3: Add routes to `finance.py`**

In `app/api/routers/finance.py`, after the existing `GET /finance/report` HTML route, add:

```python
@router.get("/report/data")
def report_data(
    household_id: str = Query(...),
    month: str = Query(default=None, description="YYYY-MM, defaults to current month"),
    db: Session = Depends(get_db),
) -> dict:
    """JSON endpoint — returns all data for the monthly report UI."""
    import datetime
    if month:
        try:
            dt = datetime.datetime.strptime(month, "%Y-%m")
            year, mon = dt.year, dt.month
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    else:
        today = datetime.date.today()
        year, mon = today.year, today.month
    return FinanceService(db).monthly_report(household_id, year, mon)
```

Also update the existing `GET /finance/report` HTML route (added in the previous session) to pass report data to the template:

```python
@router.get("/report", response_class=HTMLResponse)
def report_page(
    request: Request,
    household_id: str = Query(default=None),
    month: str = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    import datetime, json
    report_data = None
    if household_id:
        if month:
            try:
                dt = datetime.datetime.strptime(month, "%Y-%m")
                year, mon = dt.year, dt.month
            except ValueError:
                year, mon = datetime.date.today().year, datetime.date.today().month
        else:
            today = datetime.date.today()
            year, mon = today.year, today.month
        report_data = FinanceService(db).monthly_report(household_id, year, mon)
    return templates.TemplateResponse(
        "monthly_report.html",
        {"request": request, "report_data": report_data},
    )
```

- [ ] **Step 4: Run route tests**

```bash
pytest tests/test_finance_report.py -v -k "endpoint"
```

Expected: both pass.

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/finance.py tests/test_finance_report.py
git commit -m "feat(api): add /finance/report/data JSON endpoint and wire HTML route"
```

---

## Task 4: Wire template to real data

**Files:**
- Modify: `app/dashboard/templates/monthly_report.html`

When `household_id` is provided, `report_data` is a dict injected by Jinja2. When not provided (direct file open / no household), `report_data` is `None` and the template falls back to mock data. This keeps the prototype working standalone.

- [ ] **Step 1: Add Jinja2 data injection block**

In `monthly_report.html`, find the `<script>` opening tag and the `// ══ MOCK DATA` section. Replace the entire mock data block and `LEDGER` computation with:

```js
// ══════════════════════════════════════════════════════════════════════════════
// DATA — real (Jinja2-injected) or mock fallback
// ══════════════════════════════════════════════════════════════════════════════
const TODAY = '{{ today_iso }}' || new Date().toISOString().slice(0,10);
const FX_USD = 90; // mock rate — replace with real FX from backend later

{% if report_data %}
const _RAW = {{ report_data | tojson }};
const ACCOUNTS = _RAW.accounts;  // [{id, name, currency}]
const _SNAPSHOTS = _RAW.snapshots; // {account_id: {actual_balance} | null}
const _REPORT_YEAR  = _RAW.year;
const _REPORT_MONTH = _RAW.month;
{% else %}
// ── MOCK FALLBACK (no household_id provided) ──────────────────────────────
const _REPORT_YEAR = 2026, _REPORT_MONTH = 5;
const ACCOUNTS = [
  { id:'acc-1', name:'Тинькофф',     currency:'rub' },
  { id:'acc-2', name:'USD Наличные', currency:'usd' },
];
const _SNAPSHOTS = {
  'acc-1': { actual_balance: 84200 },
  'acc-2': { actual_balance: 108000 }, // $1200 in RUB equiv
};
const _RAW = { transactions: [
  { id:'tx-01', occurred_at:'2026-05-01', direction:'income',  amount:145000, currency:'rub', merchant_raw:'Зарплата — Макс',           primary_tag:'зарплата',  account_id:'acc-1', is_planned:false, status:'actual',   planned_amount:145000 },
  { id:'tx-02', occurred_at:'2026-05-01', direction:'income',  amount:92000,  currency:'rub', merchant_raw:'Зарплата — Аня',            primary_tag:'зарплата',  account_id:'acc-1', is_planned:false, status:'actual',   planned_amount:92000  },
  { id:'tx-03', occurred_at:'2026-05-03', direction:'expense', amount:4200,   currency:'rub', merchant_raw:'ВкусВилл',                  primary_tag:'продукты',  account_id:'acc-1', is_planned:false, status:'actual'   },
  { id:'tx-04', occurred_at:'2026-05-05', direction:'expense', amount:75000,  currency:'rub', merchant_raw:'Аренда кв. Красина 17',     primary_tag:'жильё',     account_id:'acc-1', is_planned:false, status:'matched',  planned_amount:75000  },
  { id:'tx-05', occurred_at:'2026-05-07', direction:'expense', amount:1390,   currency:'rub', merchant_raw:'Яндекс Плюс',               primary_tag:'подписки',  account_id:'acc-1', is_planned:false, status:'matched',  planned_amount:1390   },
  { id:'tx-06', occurred_at:'2026-05-09', direction:'expense', amount:3800,   currency:'rub', merchant_raw:'Кофе и рестораны',          primary_tag:'еда',       account_id:'acc-1', is_planned:false, status:'actual'   },
  { id:'tx-07', occurred_at:'2026-05-10', direction:'expense', amount:680,    currency:'rub', merchant_raw:'Netflix',                   primary_tag:'подписки',  account_id:'acc-1', is_planned:false, status:'mismatch', planned_amount:799   },
  { id:'tx-08', occurred_at:'2026-05-11', direction:'expense', amount:28000,  currency:'rub', merchant_raw:'Ремонт машины [сюрприз]',   primary_tag:'авто',      account_id:'acc-1', is_planned:false, status:'unplanned'},
  { id:'tx-09', occurred_at:'2026-05-14', direction:'expense', amount:5600,   currency:'rub', merchant_raw:'Перекрёсток',               primary_tag:'продукты',  account_id:'acc-1', is_planned:false, status:'actual'   },
  { id:'tx-10', occurred_at:'2026-05-15', direction:'expense', amount:2200,   currency:'rub', merchant_raw:'Такси',                     primary_tag:'транспорт', account_id:'acc-1', is_planned:false, status:'actual'   },
  { id:'tx-11', occurred_at:'2026-05-15', direction:'expense', amount:200,    currency:'usd', merchant_raw:'Airbnb deposit',            primary_tag:'поездки',   account_id:'acc-2', is_planned:false, status:'actual'   },
  { id:'tx-12', occurred_at:'2026-05-10', direction:'expense', amount:8500,   currency:'rub', merchant_raw:'Интернет + мобильный',      primary_tag:'связь',     account_id:'acc-1', is_planned:true,  status:'overdue'  },
  { id:'tx-13', occurred_at:'2026-05-20', direction:'expense', amount:15000,  currency:'rub', merchant_raw:'Фитнес-клуб',               primary_tag:'спорт',     account_id:'acc-1', is_planned:true,  status:'planned'  },
  { id:'tx-14', occurred_at:'2026-05-25', direction:'expense', amount:42000,  currency:'rub', merchant_raw:'Автостраховка ОСАГО',       primary_tag:'авто',      account_id:'acc-1', is_planned:true,  status:'planned'  },
  { id:'tx-15', occurred_at:'2026-05-28', direction:'income',  amount:145000, currency:'rub', merchant_raw:'Зарплата — Макс',           primary_tag:'зарплата',  account_id:'acc-1', is_planned:true,  status:'planned'  },
  { id:'tx-16', occurred_at:'2026-05-31', direction:'expense', amount:6000,   currency:'rub', merchant_raw:'Коммунальные услуги',       primary_tag:'жильё',     account_id:'acc-1', is_planned:true,  status:'planned'  },
], tag_summary: [] };
{% endif %}

// ── compute running balance from snapshots + sorted transactions
const ACC_START = {};
ACCOUNTS.forEach(a => {
  const snap = _SNAPSHOTS[a.id];
  const native = snap ? snap.actual_balance : 0;
  ACC_START[a.id] = a.currency === 'usd' ? native * FX_USD : native;
});
const totalStart = Object.values(ACC_START).reduce((s, v) => s + v, 0);
const sorted = [..._RAW.transactions].sort((a,b) => a.occurred_at.localeCompare(b.occurred_at));
let running = totalStart;
const LEDGER = sorted.map(tx => {
  const rubAmount = tx.currency === 'usd' ? tx.amount * FX_USD : tx.amount;
  const delta = tx.direction === 'income' ? rubAmount : -rubAmount;
  running += delta;
  return { ...tx, rubAmount, delta, running_balance: running };
});
```

- [ ] **Step 2: Pass `today_iso` from the route**

Update the `report_page` route in `app/api/routers/finance.py` to pass `today_iso`:

```python
import datetime as _dt
...
return templates.TemplateResponse(
    "monthly_report.html",
    {
        "request": request,
        "report_data": report_data,
        "today_iso": _dt.date.today().isoformat(),
    },
)
```

- [ ] **Step 3: Manual smoke test with real data**

With uvicorn running (requires `.env`):

```
http://localhost:8000/finance/report?household_id=<your-household-id>
```

Expected: page loads, shows real transactions. Without `household_id`: mock data.

- [ ] **Step 4: Smoke test with mock fallback (no server needed)**

```bash
python3 -m http.server 3333 --directory app/dashboard/templates &
open http://localhost:3333/monthly_report.html
```

Expected: Jinja2 tags render as literal strings in raw HTML → page still renders with mock data (the `{% if %}` block is plain text in a `file://` context — this is acceptable for prototype, Jinja2 only executes server-side).

Note: the `{% if report_data %}` block will be treated as a JS comment in raw-file mode. The mock fallback inside `{% else %}` will not execute either. For raw-file prototype testing, keep a separate `monthly_report_mock.html` copy or test only through the FastAPI server.

Alternative (simpler): use a JS flag instead of Jinja2 conditionals so raw-file opening still works:

```js
// Replace Jinja2 {% if %} with a runtime check:
const _INJECTED = {% if report_data %}{{ report_data | tojson }}{% else %}null{% endif %};
```

When served raw (file://), `{%` and `%}` are syntax errors → use the FastAPI server path for wired testing.

- [ ] **Step 5: Commit**

```bash
git add app/dashboard/templates/monthly_report.html app/api/routers/finance.py
git commit -m "feat(ui): wire monthly_report.html to Jinja2 real data injection"
```

---

## Verification Checklist

After all tasks complete:

- [ ] `pytest tests/ -q` — all green, no regressions
- [ ] `pytest tests/test_finance_report.py -v` — all 9 tests pass
- [ ] http://localhost:3333/monthly_report.html opens (mock data, no server needed)
- [ ] Месяц tab shows tag analytics table with sparklines below the ledger
- [ ] Switching ₽/$ converts amounts in tag analytics table
- [ ] http://localhost:8000/finance/report?household_id=X shows real data (requires server + .env)
- [ ] http://localhost:8000/finance/report/data?household_id=X&month=2026-05 returns JSON
- [ ] `git diff --stat` — only 4 files changed
