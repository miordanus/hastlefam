from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas.finance import SQLImportRequest, TransactionCorrectionUpdate
from app.application.services.finance_service import FinanceService
from app.application.services.import_service import ImportService
from app.infrastructure.db.models import FinanceCategory, RecurringPayment, Transaction

router = APIRouter(prefix="/finance", tags=["finance"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "dashboard" / "templates"))


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
        "finance_corrections.html",
        {
            "request": request,
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
        report_data = FinanceService(db).monthly_report(household_id, year, mon)
    return templates.TemplateResponse(
        "monthly_report.html",
        {
            "request": request,
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
    return FinanceService(db).monthly_report(household_id, year, mon)


@router.get("/debug/error")
def debug_error(
    household_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    """Temporary debug endpoint — returns raw exception info."""
    import datetime as _dt
    import traceback
    try:
        today = _dt.date.today()
        result = FinanceService(db).monthly_report(household_id, today.year, today.month)
        return {"ok": True, "keys": list(result.keys()) if result else None}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "trace": traceback.format_exc()}


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
