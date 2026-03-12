from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Account, Owner, RawImportTransaction, Transaction


class ImportService:
    def __init__(self, db: Session):
        self.db = db

    def import_from_sql(
        self,
        household_id: str,
        source_name: str,
        sql_query: str,
        default_currency: str = "USD",
        source_account_id: str | None = None,
        source_owner_id: str | None = None,
        force_expense_source: bool = True,
    ) -> dict[str, Any]:
        import_batch_id = f"{source_name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        rows = self.db.execute(text(sql_query)).mappings().all()

        created = 0
        duplicates = 0
        pending = 0

        resolved_account_id = self._resolve_default_account(source_account_id)
        resolved_owner_id = self._resolve_default_owner(source_owner_id)

        for row in rows:
            raw = self._save_raw(household_id, import_batch_id, source_name, dict(row))
            normalized = self._normalize_row(
                household_id=household_id,
                source_name=source_name,
                row=dict(row),
                raw_id=raw.id,
                default_currency=default_currency,
                default_account_id=resolved_account_id,
                default_owner_id=resolved_owner_id,
                force_expense_source=force_expense_source,
            )

            if normalized["status"] == "duplicate":
                duplicates += 1
                raw.normalization_status = "duplicate"
                continue

            tx = normalized["transaction"]
            if tx.parse_status == "needs_correction":
                pending += 1
            self.db.add(tx)
            created += 1
            raw.normalization_status = "normalized"

        self.db.commit()
        return {
            "import_batch_id": import_batch_id,
            "rows_seen": len(rows),
            "created": created,
            "duplicates": duplicates,
            "needs_correction": pending,
        }

    def _save_raw(self, household_id: str, batch_id: str, source_name: str, row: dict[str, Any]) -> RawImportTransaction:
        raw = RawImportTransaction(
            id=uuid.uuid4(),
            household_id=household_id,
            import_batch_id=batch_id,
            source_name=source_name,
            raw_payload=row,
            raw_occurred_at=self._parse_dt(row.get("occurred_at") or row.get("date")),
            raw_amount=self._parse_decimal(row.get("amount")),
            raw_currency=(row.get("currency") or "").upper() or None,
            raw_merchant=row.get("merchant") or row.get("merchant_raw"),
            raw_description=row.get("description") or row.get("description_raw"),
            normalization_status="pending",
        )
        self.db.add(raw)
        self.db.flush()
        return raw

    def _normalize_row(
        self,
        household_id: str,
        source_name: str,
        row: dict[str, Any],
        raw_id: uuid.UUID,
        default_currency: str,
        default_account_id: uuid.UUID | None,
        default_owner_id: uuid.UUID | None,
        force_expense_source: bool,
    ) -> dict[str, Any]:
        amount = self._parse_decimal(row.get("amount"))
        occurred_at = self._parse_dt(row.get("occurred_at") or row.get("date"))
        merchant_raw = row.get("merchant") or row.get("merchant_raw")
        description_raw = row.get("description") or row.get("description_raw")

        if amount is None:
            amount = Decimal("0")

        currency_value = (row.get("currency") or default_currency or "USD").upper()
        try:
            currency = Currency(currency_value)
        except Exception:
            currency = Currency.USD

        direction = TransactionDirection.EXPENSE if force_expense_source else self._parse_direction(row.get("direction"))
        if direction is None:
            direction = TransactionDirection.EXPENSE

        parse_status = "ok"
        parse_confidence = Decimal("0.900")
        if occurred_at is None:
            occurred_at = datetime.now(timezone.utc)
            parse_status = "needs_correction"
            parse_confidence = Decimal("0.500")
        if not merchant_raw:
            parse_status = "needs_correction"
            parse_confidence = min(parse_confidence, Decimal("0.650"))

        fingerprint = self._fingerprint(household_id, occurred_at, amount, merchant_raw or "", source_name)
        if self.db.query(Transaction).filter(Transaction.dedup_fingerprint == fingerprint).first():
            return {"status": "duplicate"}

        tx = Transaction(
            id=uuid.uuid4(),
            household_id=household_id,
            owner_id=default_owner_id,
            account_id=default_account_id,
            category_id=None,
            direction=direction,
            amount=amount,
            currency=currency,
            occurred_at=occurred_at,
            merchant_raw=merchant_raw,
            description_raw=description_raw,
            source=source_name,
            raw_import_id=raw_id,
            parse_status=parse_status,
            parse_confidence=parse_confidence,
            dedup_fingerprint=fingerprint,
        )
        return {"status": "created", "transaction": tx}

    def _resolve_default_account(self, source_account_id: str | None) -> uuid.UUID | None:
        if not source_account_id:
            return None
        account = self.db.get(Account, source_account_id)
        return account.id if account else None

    def _resolve_default_owner(self, source_owner_id: str | None) -> uuid.UUID | None:
        if not source_owner_id:
            return None
        owner = self.db.get(Owner, source_owner_id)
        return owner.id if owner else None

    @staticmethod
    def _parse_decimal(raw: Any) -> Decimal | None:
        if raw is None:
            return None
        try:
            return Decimal(str(raw))
        except Exception:
            return None

    @staticmethod
    def _parse_dt(raw: Any) -> datetime | None:
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except Exception:
                return None
        return None

    @staticmethod
    def _parse_direction(raw: Any) -> TransactionDirection | None:
        if not raw:
            return None
        try:
            return TransactionDirection(str(raw).lower())
        except Exception:
            return None

    @staticmethod
    def _fingerprint(household_id: str, occurred_at: datetime, amount: Decimal, merchant_raw: str, source_name: str) -> str:
        payload = f"{household_id}|{occurred_at.date().isoformat()}|{amount}|{merchant_raw.strip().lower()}|{source_name}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
