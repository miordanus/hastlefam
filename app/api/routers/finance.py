from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas.finance import SQLImportRequest, TransactionCorrectionUpdate
from app.application.services.finance_service import FinanceService
from app.application.services.import_service import ImportService
from app.infrastructure.config.settings import get_settings
from app.infrastructure.db.models import FinanceCategory, RecurringPayment, Transaction


def _use_rest() -> bool:
    s = get_settings()
    return bool(s.supabase_url and s.supabase_service_role_key)


def _run_monthly_report(db: Session, household_id: str, year: int, month: int) -> dict:
    if _use_rest():
        return FinanceService(None).monthly_report_via_rest(household_id, year, month)
    return FinanceService(db).monthly_report(household_id, year, month)


def _run_cashflow(db: Session, household_id: str, sd, ed) -> dict:
    if _use_rest():
        return FinanceService(None).cashflow_monthly_via_rest(household_id, sd, ed)
    return FinanceService(db).cashflow_monthly(household_id, sd, ed)

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
def transaction_action(tx_id: str, action: str = Form(...)) -> dict:
    """Inline action for ledger rows. action='paid' converts a planned tx to actual;
    action='skip' marks it skipped. Requires Supabase REST creds."""
    if not _use_rest():
        raise HTTPException(status_code=503, detail="Supabase REST not configured")
    if action == "paid":
        body = {"is_planned": False}
    elif action == "skip":
        body = {"is_skipped": True}
    else:
        raise HTTPException(status_code=400, detail="action must be 'paid' or 'skip'")
    from app.infrastructure.supabase import SupabaseClient
    s = get_settings()
    with SupabaseClient(s.supabase_url, s.supabase_service_role_key) as sb:
        sb.patch("transactions", {"id": f"eq.{tx_id}"}, body)
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

