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


@router.post("/corrections/{transaction_id}")
def update_correction(
    transaction_id: str,
    household_id: str = Form(...),
    uncategorized: bool = Form(False),
    category_id: str | None = Form(None),
    recurring_payment_id: str | None = Form(None),
    db: Session = Depends(get_db),
):
    _ = TransactionCorrectionUpdate(category_id=category_id or None, recurring_payment_id=recurring_payment_id or None)
    tx = db.get(Transaction, transaction_id)
    if tx:
        tx.category_id = category_id or None
        if recurring_payment_id:
            tx.description = f"linked_recurring:{recurring_payment_id}"
        db.commit()
    return RedirectResponse(
        url=f"/finance/corrections?household_id={household_id}&uncategorized={str(uncategorized).lower()}",
        status_code=303,
    )
