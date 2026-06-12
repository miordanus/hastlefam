from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas.finance import (
    AccountCreate,
    BalanceSnapshotCreate,
    BudgetUpsert,
    BulkTagRequest,
    RecurringCreate,
    SQLImportRequest,
    TransactionCorrectionUpdate,
    TransactionCreate,
    TransactionUpdate,
)
from app.application.services.finance_service import FinanceService
from app.application.services.import_service import ImportService
from app.infrastructure.config.settings import get_settings
from app.infrastructure.db.models import FinanceCategory, RecurringPayment, Transaction


def _use_rest() -> bool:
    s = get_settings()
    return bool(s.supabase_url and s.supabase_service_role_key)


def _as_dt_iso(d) -> str:
    """A date → midnight-UTC ISO datetime string for PostgREST writes."""
    import datetime as _dt
    if isinstance(d, _dt.datetime):
        return d.isoformat()
    return _dt.datetime(d.year, d.month, d.day, tzinfo=_dt.timezone.utc).isoformat()


def _run_monthly_report(db: Session, household_id: str, year: int, month: int) -> dict:
    if _use_rest():
        return FinanceService(None).monthly_report_via_rest(household_id, year, month)
    return FinanceService(db).monthly_report(household_id, year, month)


def _run_cashflow(db: Session, household_id: str, sd, ed) -> dict:
    if _use_rest():
        return FinanceService(None).cashflow_monthly_via_rest(household_id, sd, ed)
    return FinanceService(db).cashflow_monthly(household_id, sd, ed)


def _run_data_health(db: Session, household_id: str, current_user_id: str | None = None) -> dict:
    if _use_rest():
        return FinanceService(None).data_health_via_rest(household_id, current_user_id)
    return FinanceService(db).data_health(household_id, current_user_id)


def _run_planned(db: Session, household_id: str) -> dict:
    if _use_rest():
        return FinanceService(None).planned_workbench_via_rest(household_id)
    return FinanceService(db).planned_workbench(household_id)


def _run_forecast(db: Session, household_id: str) -> dict:
    if _use_rest():
        return FinanceService(None).forecast_by_week_via_rest(household_id)
    return FinanceService(db).forecast_by_week(household_id)


def _run_quality(db: Session, household_id: str) -> dict:
    if _use_rest():
        return FinanceService(None).untagged_transactions_via_rest(household_id)
    return FinanceService(db).untagged_transactions(household_id)


def _run_accounts(db: Session, household_id: str) -> dict:
    if _use_rest():
        return FinanceService(None).list_accounts_with_balances_via_rest(household_id)
    return FinanceService(db).list_accounts_with_balances(household_id)


def _run_recurring(db: Session, household_id: str) -> dict:
    if _use_rest():
        return FinanceService(None).list_recurring_via_rest(household_id)
    return FinanceService(db).list_recurring(household_id)


def _is_locked(db: Session, household_id: str, ym: str) -> bool:
    # Fail-open: if lock state can't be read (e.g. month_lock table not yet
    # migrated), treat the month as open rather than 500-ing every write.
    try:
        if _use_rest():
            return FinanceService.is_month_locked_via_rest(household_id, ym)
        return FinanceService(db).is_month_locked(household_id, ym)
    except Exception:
        return False


def _ym_of(d) -> str:
    """YYYY-MM for a date/datetime."""
    return f"{d.year:04d}-{d.month:02d}"


def _assert_unlocked(db: Session, household_id: str, ym: str) -> None:
    if household_id and _is_locked(db, household_id, ym):
        raise HTTPException(status_code=423, detail="Месяц закрыт и заблокирован для изменений")


def _tx_meta(db: Session, tx_id: str) -> tuple[str | None, str | None]:
    """(household_id, YYYY-MM) for a transaction, for lock enforcement on edit/action.
    Returns (None, None) if it can't be resolved (no guard applied)."""
    try:
        if _use_rest():
            from app.infrastructure.supabase import SupabaseClient
            s = get_settings()
            with SupabaseClient(s.supabase_url, s.supabase_service_role_key) as sb:
                rows = sb.get("transactions", {"select": "household_id,occurred_at", "id": f"eq.{tx_id}"})
            if not rows:
                return None, None
            occ = (rows[0].get("occurred_at") or "")[:7]  # YYYY-MM
            return rows[0].get("household_id"), (occ or None)
        import uuid as _u
        tid = _u.UUID(tx_id) if isinstance(tx_id, str) else tx_id
        tx = db.get(Transaction, tid)
        if tx is None or tx.occurred_at is None:
            return (str(tx.household_id) if tx else None), None
        return str(tx.household_id), _ym_of(tx.occurred_at)
    except Exception:
        return None, None

router = APIRouter(prefix="/finance", tags=["finance"])

_TEMPLATE_DIR = str(Path(__file__).resolve().parents[2] / "dashboard" / "templates")
import jinja2 as _jinja2
_env = _jinja2.Environment(
    loader=_jinja2.FileSystemLoader(_TEMPLATE_DIR),
    autoescape=_jinja2.select_autoescape(),
    cache_size=0,
)
templates = Jinja2Templates(env=_env)


@router.post("/import/sql")
def sql_import(payload: SQLImportRequest, db: Session = Depends(get_db)) -> dict:
    result = ImportService(db).import_from_sql(**payload.model_dump())
    return result


@router.get("/month")
def month_summary(household_id: str = Query(...), db: Session = Depends(get_db)) -> dict:
    return FinanceService(db).month_summary(household_id)


@router.get("/upcoming")
def upcoming(household_id: str = Query(...), days: int = Query(7, ge=1, le=30), db: Session = Depends(get_db)) -> dict:
    items = FinanceService(db).upcoming_payments(household_id, days)
    return {"items": items}


@router.get("/corrections", response_class=HTMLResponse)
def corrections_page(
    request: Request,
    household_id: str = Query(...),
    uncategorized: bool = Query(False),
    db: Session = Depends(get_db),
):
    tx_query = db.query(Transaction).filter(Transaction.household_id == household_id)
    if uncategorized:
        tx_query = tx_query.filter(Transaction.category_id.is_(None))

    tx_rows = tx_query.order_by(Transaction.occurred_at.desc()).limit(100).all()
    categories = db.query(FinanceCategory).filter(
        (FinanceCategory.household_id == household_id) | (FinanceCategory.household_id.is_(None))
    ).order_by(FinanceCategory.name.asc()).all()
    recurring = db.query(RecurringPayment).filter(RecurringPayment.household_id == household_id).all()

    return templates.TemplateResponse(
        request,
        "finance_corrections.html",
        {
            "household_id": household_id,
            "uncategorized": uncategorized,
            "transactions": tx_rows,
            "categories": categories,
            "recurring": recurring,
        },
    )


@router.get("/report", response_class=HTMLResponse)
def report_page(
    request: Request,
    household_id: str = Query(default=None),
    month: str = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    import datetime as _dt
    report_data = None
    if household_id:
        if month:
            try:
                dt = _dt.datetime.strptime(month, "%Y-%m")
                year, mon = dt.year, dt.month
            except ValueError:
                today = _dt.date.today()
                year, mon = today.year, today.month
        else:
            today = _dt.date.today()
            year, mon = today.year, today.month
        report_data = _run_monthly_report(db, household_id, year, mon)
    return templates.TemplateResponse(
        request,
        "monthly_report.html",
        {
            "report_data": report_data,
            "today_iso": _dt.date.today().isoformat(),
            "household_id": household_id,
        },
    )


@router.get("/report/data")
def report_data(
    household_id: str = Query(...),
    month: str = Query(default=None, description="YYYY-MM, defaults to current month"),
    db: Session = Depends(get_db),
) -> dict:
    """JSON endpoint — returns all data for the monthly report UI."""
    import datetime as _dt
    if month:
        try:
            dt = _dt.datetime.strptime(month, "%Y-%m")
            year, mon = dt.year, dt.month
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    else:
        today = _dt.date.today()
        year, mon = today.year, today.month
    return _run_monthly_report(db, household_id, year, mon)


@router.get("/health", response_class=HTMLResponse)
def health_page(
    request: Request,
    household_id: str = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Data-health home page (authed landing). Shows data completeness +
    freshness + a per-person to-do split."""
    hid = household_id or getattr(request.state, "household_id", None)
    uid = getattr(request.state, "user_id", None)
    health_data = _run_data_health(db, hid, uid) if hid else None
    return templates.TemplateResponse(
        request,
        "data_health.html",
        {"health_data": health_data, "household_id": hid},
    )


@router.get("/health/data")
def health_data(
    request: Request,
    household_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    """JSON endpoint — same payload the data-health page renders."""
    return _run_data_health(db, household_id, getattr(request.state, "user_id", None))


@router.get("/planned", response_class=HTMLResponse)
def planned_page(
    request: Request,
    household_id: str = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Planned-items workbench (#2): close / reschedule / skip in one place."""
    hid = household_id or getattr(request.state, "household_id", None)
    data = _run_planned(db, hid) if hid else None
    if data and hid:
        try:
            forecast = _run_forecast(db, hid)
            data["forecast_weeks"] = forecast.get("weeks", [])
        except Exception:
            data["forecast_weeks"] = []
    return templates.TemplateResponse(
        request,
        "planned.html",
        {"planned_data": data, "household_id": hid},
    )


@router.get("/planned/data")
def planned_data(
    household_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    """JSON endpoint — planned workbench payload."""
    data = _run_planned(db, household_id)
    try:
        forecast = _run_forecast(db, household_id)
        data["forecast_weeks"] = forecast.get("weeks", [])
    except Exception:
        data["forecast_weeks"] = []
    return data


@router.get("/quality", response_class=HTMLResponse)
def quality_page(
    request: Request,
    household_id: str = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Quality tab (#4): bulk-tag untagged transactions fast, without opening each."""
    hid = household_id or getattr(request.state, "household_id", None)
    data = _run_quality(db, hid) if hid else None
    return templates.TemplateResponse(
        request,
        "quality.html",
        {"quality_data": data, "household_id": hid},
    )


@router.get("/quality/data")
def quality_data(
    household_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    """JSON endpoint — untagged transactions + tag suggestions."""
    return _run_quality(db, household_id)


@router.post("/transactions/bulk_tag")
def bulk_tag(body: BulkTagRequest, db: Session = Depends(get_db)) -> dict:
    """Apply many {tx_id, tag} assignments at once (Quality tab). Dual-path."""
    assignments = [a.model_dump() for a in body.assignments]
    if _use_rest():
        return FinanceService.bulk_tag_via_rest(assignments)
    return FinanceService(db).bulk_tag(assignments)


@router.get("/accounts", response_class=HTMLResponse)
def accounts_page(
    request: Request,
    household_id: str = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Accounts management (#5): add accounts and see the merge to a single RUB total."""
    hid = household_id or getattr(request.state, "household_id", None)
    data = _run_accounts(db, hid) if hid else None
    return templates.TemplateResponse(
        request,
        "accounts.html",
        {"accounts_data": data, "household_id": hid},
    )


@router.get("/accounts/data")
def accounts_data(
    household_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    """JSON endpoint — accounts with per-account RUB + consolidated total."""
    return _run_accounts(db, household_id)


@router.post("/accounts")
def create_account(body: AccountCreate, db: Session = Depends(get_db)) -> dict:
    """Create an account from the web UI. Dual-path (REST on Vercel, else SQLAlchemy)."""
    if _use_rest():
        return FinanceService(None).create_account_via_rest(
            body.household_id, body.name, body.currency,
            owner_user_id=body.owner_user_id, is_shared=body.is_shared,
        )
    from app.domain.enums import Currency as _Cur
    acc = FinanceService(db).create_account(
        body.household_id, body.name, _Cur(body.currency),
        owner_user_id=body.owner_user_id, is_shared=body.is_shared,
    )
    return {"ok": True, "id": str(acc.id)}


@router.get("/recurring", response_class=HTMLResponse)
def recurring_page(
    request: Request,
    household_id: str = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Recurring payments management — list, add, deactivate (mirrors bot /recurring)."""
    hid = household_id or getattr(request.state, "household_id", None)
    data = _run_recurring(db, hid) if hid else None
    return templates.TemplateResponse(
        request,
        "recurring.html",
        {"recurring_data": data, "household_id": hid},
    )


@router.get("/recurring/data")
def recurring_data(household_id: str = Query(...), db: Session = Depends(get_db)) -> dict:
    """JSON endpoint — active recurring payments."""
    return _run_recurring(db, household_id)


@router.post("/recurring")
def create_recurring(body: RecurringCreate, db: Session = Depends(get_db)) -> dict:
    """Create a monthly recurring payment from the web UI. Dual-path."""
    if not (1 <= body.day_of_month <= 31):
        raise HTTPException(status_code=422, detail="day_of_month must be 1–31")
    if _use_rest():
        rid = FinanceService(None).create_recurring_via_rest(
            body.household_id, title=body.title, amount=body.amount,
            currency=body.currency, day_of_month=body.day_of_month,
        )
    else:
        rid = FinanceService(db).create_recurring(
            body.household_id, title=body.title, amount=body.amount,
            currency=body.currency, day_of_month=body.day_of_month,
        )
    return {"ok": True, "id": rid}


@router.post("/recurring/{rec_id}/deactivate")
def deactivate_recurring(rec_id: str, db: Session = Depends(get_db)) -> dict:
    """Soft-delete a recurring payment (is_active=False). Dual-path."""
    if _use_rest():
        FinanceService(None).deactivate_recurring_via_rest(rec_id)
        return {"ok": True, "id": rec_id}
    ok = FinanceService(db).deactivate_recurring(rec_id)
    if not ok:
        raise HTTPException(status_code=404, detail="recurring payment not found")
    return {"ok": True, "id": rec_id}


@router.get("/months/lock/status")
def month_lock_status(
    household_id: str = Query(...),
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
) -> dict:
    """Lock state + approved totals snapshot for a month (#6)."""
    if _use_rest():
        return FinanceService(None).month_lock_status_via_rest(household_id, month)
    return FinanceService(db).month_lock_status(household_id, month)


@router.post("/months/lock")
def lock_month(
    request: Request,
    household_id: str = Form(...),
    month: str = Form(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
) -> dict:
    """Approve & lock a month: snapshot actual income/expense and freeze edits (#6)."""
    uid = getattr(request.state, "user_id", None)
    if _use_rest():
        return FinanceService(None).lock_month_via_rest(household_id, month, uid)
    return FinanceService(db).lock_month(household_id, month, uid)


@router.post("/months/unlock")
def unlock_month(
    household_id: str = Form(...),
    month: str = Form(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
) -> dict:
    """Reopen a previously locked month for edits (#6)."""
    if _use_rest():
        return FinanceService(None).unlock_month_via_rest(household_id, month)
    return FinanceService(db).unlock_month(household_id, month)


@router.get("/cashflow")
def cashflow_monthly(
    household_id: str = Query(...),
    start: str = Query(default=None, description="YYYY-MM, defaults to current month"),
    end: str = Query(default=None, description="YYYY-MM, defaults to start + 2 months"),
    db: Session = Depends(get_db),
) -> dict:
    """Monthly cashflow aggregate (Cashflow tab). Planned items only."""
    import datetime as _dt

    today = _dt.date.today()
    if start:
        try:
            sd = _dt.datetime.strptime(start, "%Y-%m").date()
        except ValueError:
            raise HTTPException(status_code=422, detail="start must be YYYY-MM")
    else:
        sd = today.replace(day=1)

    if end:
        try:
            ed = _dt.datetime.strptime(end, "%Y-%m").date()
        except ValueError:
            raise HTTPException(status_code=422, detail="end must be YYYY-MM")
    else:
        y, m = sd.year, sd.month + 2
        while m > 12:
            m -= 12
            y += 1
        ed = _dt.date(y, m, 1)

    return _run_cashflow(db, household_id, sd, ed)


@router.post("/transactions/{tx_id}/action")
def transaction_action(tx_id: str, action: str = Form(...), db: Session = Depends(get_db)) -> dict:
    """Inline action for ledger rows. action='paid' converts a planned tx to actual;
    action='skip' marks it skipped. Dual-path (REST on Vercel, else SQLAlchemy)."""
    if action == "paid":
        body = {"is_planned": False}
    elif action == "skip":
        body = {"is_skipped": True}
    else:
        raise HTTPException(status_code=400, detail="action must be 'paid' or 'skip'")
    hh, ym = _tx_meta(db, tx_id)
    if ym:
        _assert_unlocked(db, hh, ym)
    if _use_rest():
        from app.infrastructure.supabase import SupabaseClient
        s = get_settings()
        with SupabaseClient(s.supabase_url, s.supabase_service_role_key) as sb:
            sb.patch("transactions", {"id": f"eq.{tx_id}"}, body)
        return {"ok": True, "tx_id": tx_id, "action": action}
    tx = FinanceService(db).mark_transaction(tx_id, **body)
    if tx is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    return {"ok": True, "tx_id": tx_id, "action": action}


@router.get("/report/range")
def report_range(
    household_id: str = Query(...),
    from_: str = Query(..., alias="from", description="YYYY-MM"),
    to_:   str = Query(..., alias="to",   description="YYYY-MM"),
) -> dict:
    """Per-month income/expense totals (RUB) for [from..to] inclusive.

    Each month row carries both actual_* and planned_* fields so the dashboard
    can render upcoming planned amounts without inflating actual totals.
    """
    if not _use_rest():
        raise HTTPException(status_code=503, detail="Supabase REST not configured")
    for ym in (from_, to_):
        try:
            y, m = [int(x) for x in ym.split("-")]
            if not (1 <= m <= 12):
                raise ValueError
        except ValueError:
            raise HTTPException(status_code=422, detail="from/to must be YYYY-MM")
    rows = FinanceService(None).monthly_totals_via_rest(household_id, from_, to_)
    return {"months": rows}


@router.post("/corrections/{transaction_id}")
def update_correction(
    transaction_id: str,
    household_id: str = Form(...),
    uncategorized: bool = Form(False),
    primary_tag: str | None = Form(None),
    db: Session = Depends(get_db),
):
    tx = db.get(Transaction, transaction_id)
    if tx:
        tag = (primary_tag or "").strip().lower() or None
        tx.primary_tag = tag
        db.commit()
    return RedirectResponse(
        url=f"/finance/corrections?household_id={household_id}&uncategorized={str(uncategorized).lower()}",
        status_code=303,
    )


@router.post("/transactions")
def create_transaction(body: TransactionCreate, db: Session = Depends(get_db)) -> dict:
    """Add a transaction from the web UI. REST write on Vercel, else SQLAlchemy."""
    _assert_unlocked(db, body.household_id, _ym_of(body.occurred_at))
    if _use_rest():
        import uuid as _u

        from app.domain.enums import Currency, TransactionDirection
        s = get_settings()
        tx_id = str(_u.uuid4())
        occ = _as_dt_iso(body.occurred_at)
        cur = Currency(body.currency).value
        dir_ = TransactionDirection(body.direction).value
        tag = FinanceService._clean_tag(body.primary_tag)
        fp = FinanceService._web_fingerprint(
            body.household_id, body.amount, cur, body.merchant, body.occurred_at.isoformat(), dir_
        )
        row = {
            "id": tx_id,
            "household_id": body.household_id,
            "user_id": body.user_id,
            "account_id": body.account_id,
            "direction": dir_,
            "amount": float(body.amount),
            "currency": cur,
            "occurred_at": occ,
            "merchant_raw": body.merchant,
            "source": "web",
            "parse_status": "ok",
            "primary_tag": tag,
            "extra_tags": [],
            "is_planned": body.is_planned,
            "is_internal_transfer": False,
            "is_skipped": False,
            "dedup_fingerprint": fp,
        }
        from app.infrastructure.supabase import SupabaseClient
        with SupabaseClient(s.supabase_url, s.supabase_service_role_key) as sb:
            sb.post("transactions", [row])
        return {"ok": True, "id": tx_id}

    tx = FinanceService(db).create_transaction(
        household_id=body.household_id, amount=body.amount, currency=body.currency,
        direction=body.direction, occurred_at=body.occurred_at, primary_tag=body.primary_tag,
        account_id=body.account_id, merchant=body.merchant, user_id=body.user_id,
        is_planned=body.is_planned,
    )
    return {"ok": True, "id": str(tx.id)}


@router.post("/transactions/{tx_id}/edit")
def edit_transaction(tx_id: str, body: TransactionUpdate, db: Session = Depends(get_db)) -> dict:
    """Edit a transaction's fields from the web UI. REST or SQLAlchemy."""
    fields = body.model_dump(exclude_unset=True)
    # Lock enforcement: block edits within a locked month, and block rescheduling
    # a transaction into or out of a locked month.
    hh, ym = _tx_meta(db, tx_id)
    if ym:
        _assert_unlocked(db, hh, ym)
    if fields.get("occurred_at") and hh:
        _assert_unlocked(db, hh, _ym_of(fields["occurred_at"]))
    if _use_rest():
        from app.domain.enums import Currency, TransactionDirection
        patch: dict = {}
        if "amount" in fields and fields["amount"] is not None:
            patch["amount"] = float(fields["amount"])
        if fields.get("currency"):
            patch["currency"] = Currency(fields["currency"]).value
        if fields.get("direction"):
            patch["direction"] = TransactionDirection(fields["direction"]).value
        if fields.get("occurred_at"):
            patch["occurred_at"] = _as_dt_iso(fields["occurred_at"])
        if "primary_tag" in fields:
            patch["primary_tag"] = FinanceService._clean_tag(fields["primary_tag"])
        if fields.get("account_id"):
            patch["account_id"] = fields["account_id"]
        if fields.get("merchant") is not None:
            patch["merchant_raw"] = fields["merchant"]
        if "applied_rate_override" in fields:  # explicit null clears it
            v = fields["applied_rate_override"]
            patch["applied_rate_override"] = float(v) if v is not None else None
        if not patch:
            return {"ok": True, "tx_id": tx_id, "unchanged": True}
        from app.infrastructure.supabase import SupabaseClient
        s = get_settings()
        with SupabaseClient(s.supabase_url, s.supabase_service_role_key) as sb:
            sb.patch("transactions", {"id": f"eq.{tx_id}"}, patch)
        return {"ok": True, "tx_id": tx_id}

    tx = FinanceService(db).update_transaction(tx_id, **fields)
    if tx is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    return {"ok": True, "tx_id": tx_id}


@router.get("/budgets")
def list_budgets(
    household_id: str = Query(...),
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
) -> dict:
    """Per-tag budget status (limit / spent / remaining) for the month.

    REST-aware: the deployed web is REST-only, so SQLAlchemy here would 500.
    """
    if _use_rest():
        from app.application.services.budget_service import get_budget_status_via_rest
        return {"budgets": get_budget_status_via_rest(household_id, month)}
    from app.application.services.budget_service import get_budget_status
    return {"budgets": get_budget_status(household_id, month, db)}


@router.post("/budgets")
def upsert_budget(body: BudgetUpsert, db: Session = Depends(get_db)) -> dict:
    """Create or update a per-tag monthly budget limit. REST or SQLAlchemy."""
    tag = FinanceService._clean_tag(body.tag) or ""
    if _use_rest():
        from app.infrastructure.supabase import SupabaseClient
        import uuid as _u
        s = get_settings()
        with SupabaseClient(s.supabase_url, s.supabase_service_role_key) as sb:
            existing = sb.get("tag_budgets", {
                "select": "id",
                "household_id": f"eq.{body.household_id}",
                "month_key": f"eq.{body.month_key}",
                "tag": f"eq.{tag}",
            })
            patch = {"limit_amount": float(body.limit_amount), "currency": body.currency}
            if body.rollover_enabled is not None:
                patch["rollover_enabled"] = body.rollover_enabled
            if existing:
                bid = existing[0]["id"]
                sb.patch("tag_budgets", {"id": f"eq.{bid}"}, patch)
            else:
                bid = str(_u.uuid4())
                sb.post("tag_budgets", [{
                    "id": bid,
                    "household_id": body.household_id,
                    "month_key": body.month_key,
                    "tag": tag,
                    "limit_amount": float(body.limit_amount),
                    "currency": body.currency,
                    "rollover_enabled": bool(body.rollover_enabled),
                    "rollover_amount": 0,
                }])
        return {"ok": True, "id": bid, "tag": tag, "limit_amount": float(body.limit_amount)}

    b = FinanceService(db).upsert_tag_budget(
        body.household_id, body.month_key, body.tag, body.limit_amount,
        currency=body.currency, rollover_enabled=body.rollover_enabled,
    )
    return {"ok": True, "id": str(b.id), "tag": b.tag, "limit_amount": float(b.limit_amount)}


@router.post("/balances")
def record_balance(body: BalanceSnapshotCreate, request: Request, db: Session = Depends(get_db)) -> dict:
    """Record a current-balance snapshot from the web (the bot's 🔄 Сверить).
    The discrepancy vs. transactions surfaces as drift on the data-health page."""
    uid = getattr(request.state, "user_id", None)
    if _use_rest():
        import datetime as _dt
        import uuid as _u
        sid = str(_u.uuid4())
        row = {
            "id": sid,
            "household_id": body.household_id,
            "account_id": body.account_id,
            "actual_balance": float(body.actual_balance),
            "note": body.note,
            "created_by_user_id": uid,
            "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        }
        from app.infrastructure.supabase import SupabaseClient
        s = get_settings()
        with SupabaseClient(s.supabase_url, s.supabase_service_role_key) as sb:
            sb.post("balance_snapshots", [row])
        return {"ok": True, "snapshot_id": sid}

    snap, _ = FinanceService(db).update_balance_snapshot(
        body.account_id, body.household_id, body.actual_balance, uid,
    )
    return {"ok": True, "snapshot_id": str(snap.id)}


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

