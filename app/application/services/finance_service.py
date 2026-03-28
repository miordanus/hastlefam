from __future__ import annotations

import calendar
import uuid as _uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

# ЗАКОН: get_monthly_actual() фильтрует is_planned=False.
# get_planned_total() фильтрует is_planned=True AND occurred_at > now().
# Смешивать нельзя нигде. Проверяй каждый новый запрос.

from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Account, BalanceSnapshot, PlannedPayment, Transaction


class FinanceService:
    def __init__(self, db: Session):
        self.db = db

    # ─── Month summary ────────────────────────────────────────────────────────

    def month_summary(self, household_id: str, for_date: date | None = None) -> dict[str, Any]:
        today = for_date or datetime.now(timezone.utc).date()
        month_start = today.replace(day=1)
        month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id

        month_start_dt = datetime(month_start.year, month_start.month, month_start.day, tzinfo=timezone.utc)
        # Use full calendar month end so past-month navigation shows all data
        month_end_dt = datetime(month_end.year, month_end.month, month_end.day, 23, 59, 59, tzinfo=timezone.utc)

        rows = (
            self.db.query(Transaction)
            .filter(
                Transaction.household_id == hid,
                Transaction.occurred_at >= month_start_dt,
                Transaction.occurred_at <= month_end_dt,
                Transaction.direction != TransactionDirection.TRANSFER,
                Transaction.is_planned == False,  # noqa: E712 — ЗАКОН: actual only
            )
            .all()
        )

        # Per-currency totals
        spend_by_currency: dict[str, Decimal] = {}
        income_by_currency: dict[str, Decimal] = {}
        # by_tag: {tag: {currency: amount}}
        by_tag: dict[str, dict[str, Decimal]] = {}
        untagged_count = 0
        expense_count = 0
        income_count = 0

        for tx in rows:
            if tx.direction == TransactionDirection.EXCHANGE:
                continue  # Exchange is never income or expense

            amount = Decimal(str(tx.amount))
            cur = tx.currency.value if tx.currency else "RUB"

            if tx.direction == TransactionDirection.EXPENSE:
                expense_count += 1
                spend_by_currency[cur] = spend_by_currency.get(cur, Decimal("0")) + amount
                if tx.primary_tag:
                    tag_currencies = by_tag.setdefault(tx.primary_tag, {})
                    tag_currencies[cur] = tag_currencies.get(cur, Decimal("0")) + amount
                else:
                    untagged_count += 1
            elif tx.direction == TransactionDirection.INCOME:
                income_count += 1
                income_by_currency[cur] = income_by_currency.get(cur, Decimal("0")) + amount

        # Sort tags by total amount across all currencies
        tag_totals = {tag: sum(curs.values()) for tag, curs in by_tag.items()}
        top_tag_names = sorted(tag_totals, key=lambda t: tag_totals[t], reverse=True)[:5]
        top_tags = [
            {"tag": tag, "by_currency": by_tag[tag], "amount": tag_totals[tag]}
            for tag in top_tag_names
        ]

        upcoming = self.upcoming_planned(household_id, until_date=month_end)

        return {
            "period": {"month_start": month_start.isoformat(), "today": today.isoformat()},
            "spend_by_currency": spend_by_currency,
            "income_by_currency": income_by_currency,
            "top_tags": top_tags,
            "upcoming_until_month_end": upcoming,
            "untagged_count": untagged_count,
            "expense_count": expense_count,
            "income_count": income_count,
            # Legacy keys kept for existing API routes
            "totals": {
                "spend_mtd": sum(spend_by_currency.values(), Decimal("0")),
                "income_mtd": sum(income_by_currency.values(), Decimal("0")),
            },
            "top_categories": [{"category": t["tag"], "amount": t["amount"]} for t in top_tags],
            "biggest_expenses": [],
        }

    def daily_status_summary(self, household_id: str) -> dict[str, Any]:
        """Content for the 10:00 MSK daily push."""
        today = datetime.now(timezone.utc).date()
        soon_until = today + timedelta(days=3)
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id

        month_start = today.replace(day=1)
        month_start_dt = datetime(month_start.year, month_start.month, month_start.day, tzinfo=timezone.utc)
        today_end_dt = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=timezone.utc)

        rows = (
            self.db.query(Transaction)
            .filter(
                Transaction.household_id == hid,
                Transaction.occurred_at >= month_start_dt,
                Transaction.occurred_at <= today_end_dt,
                Transaction.is_planned == False,  # noqa: E712 — ЗАКОН: actual only
            )
            .all()
        )

        spend_by_currency: dict[str, Decimal] = {}
        income_by_currency: dict[str, Decimal] = {}
        untagged_count = 0

        for tx in rows:
            if tx.direction == TransactionDirection.EXCHANGE:
                continue
            amount = Decimal(str(tx.amount))
            cur = tx.currency.value if tx.currency else "RUB"
            if tx.direction == TransactionDirection.EXPENSE:
                spend_by_currency[cur] = spend_by_currency.get(cur, Decimal("0")) + amount
                if not tx.primary_tag:
                    untagged_count += 1
            elif tx.direction == TransactionDirection.INCOME:
                income_by_currency[cur] = income_by_currency.get(cur, Decimal("0")) + amount

        planned_soon = self.upcoming_planned(household_id, until_date=soon_until)

        return {
            "spend_by_currency": spend_by_currency,
            "income_by_currency": income_by_currency,
            "planned_soon": planned_soon,
            "untagged_count": untagged_count,
        }

    # ─── Planned totals (is_planned=True) ────────────────────────────────────

    def get_planned_total(self, household_id: str, year: int, month: int) -> dict[str, Decimal]:
        """Sum of planned (is_planned=True) future transactions for the month, per currency.

        ЗАКОН: фильтр is_planned=True AND occurred_at > now().
        """
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id
        now = datetime.now(timezone.utc)
        month_start = datetime(year, month, 1, tzinfo=timezone.utc)
        last_day = calendar.monthrange(year, month)[1]
        month_end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)

        rows = (
            self.db.query(Transaction)
            .filter(
                Transaction.household_id == hid,
                Transaction.occurred_at >= month_start,
                Transaction.occurred_at <= month_end,
                Transaction.occurred_at > now,
                Transaction.is_planned == True,  # noqa: E712 — ЗАКОН: planned only
                Transaction.direction == TransactionDirection.EXPENSE,
            )
            .all()
        )

        totals: dict[str, Decimal] = {}
        for tx in rows:
            cur = tx.currency.value if tx.currency else "RUB"
            totals[cur] = totals.get(cur, Decimal("0")) + Decimal(str(tx.amount))
        return totals

    # ─── Planned payments ─────────────────────────────────────────────────────

    def upcoming_planned(self, household_id: str, days: int = 7, until_date: date | None = None) -> list[dict[str, Any]]:
        """Planned payments (not recurring) due within the given window."""
        today = datetime.now(timezone.utc).date()
        last_day = until_date or (today + timedelta(days=days))
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id

        rows = (
            self.db.query(PlannedPayment)
            .filter(
                PlannedPayment.household_id == hid,
                PlannedPayment.status == "planned",
                PlannedPayment.due_date >= today,
                PlannedPayment.due_date <= last_day,
            )
            .order_by(PlannedPayment.due_date.asc())
            .all()
        )

        return [
            {
                "id": str(r.id),
                "title": r.title,
                "amount": r.amount,
                "currency": r.currency.value,
                "due_date": r.due_date.isoformat(),
                "primary_tag": r.primary_tag,
            }
            for r in rows
        ]

    def create_planned_payment(
        self,
        household_id: str,
        title: str,
        amount: Decimal,
        currency: Currency,
        due_date: date,
        primary_tag: str | None = None,
        linked_transaction_id: str | None = None,
    ) -> PlannedPayment:
        import uuid
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id
        pp = PlannedPayment(
            id=uuid.uuid4(),
            household_id=hid,
            title=title,
            amount=amount,
            currency=currency,
            due_date=due_date,
            primary_tag=primary_tag,
            extra_tags=[],
            status="planned",
            linked_transaction_id=_uuid.UUID(linked_transaction_id) if linked_transaction_id else None,
        )
        self.db.add(pp)
        self.db.commit()
        return pp

    def mark_paid(self, planned_payment_id: str, user_id: str, household_id: str) -> Transaction | None:
        """
        Convert a planned payment into an actual transaction.
        Sets planned_payment status to 'paid'.
        Returns the new transaction (not double-counted in summaries — only
        transactions with direction EXPENSE/INCOME are aggregated, not the
        planned_payments row).
        """
        import uuid as _u
        pp = self.db.query(PlannedPayment).filter(
            PlannedPayment.id == _u.UUID(planned_payment_id)
        ).first()
        if not pp or pp.status != "planned":
            return None

        tx = Transaction(
            id=_u.uuid4(),
            household_id=pp.household_id,
            user_id=_u.UUID(user_id),
            direction=TransactionDirection.EXPENSE,
            amount=pp.amount,
            currency=pp.currency,
            occurred_at=datetime.now(timezone.utc),
            merchant_raw=pp.title,
            source="telegram",
            parse_status="ok",
            primary_tag=pp.primary_tag,
            extra_tags=pp.extra_tags or [],
        )
        self.db.add(tx)
        pp.status = "paid"
        pp.linked_transaction_id = tx.id
        self.db.commit()
        return tx

    def upcoming_transactions(self, household_id: str) -> list[dict[str, Any]]:
        """Planned transactions not yet skipped: is_planned=True, is_skipped=False, occurred_at > now."""
        today = datetime.now(timezone.utc).date()
        tomorrow_dt = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) + timedelta(days=1)
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id

        rows = (
            self.db.query(Transaction)
            .filter(
                Transaction.household_id == hid,
                Transaction.is_planned.is_(True),
                Transaction.is_skipped.is_(False),
                Transaction.occurred_at >= tomorrow_dt,
                Transaction.direction != TransactionDirection.TRANSFER,
                Transaction.direction != TransactionDirection.EXCHANGE,
            )
            .order_by(Transaction.occurred_at.asc())
            .all()
        )

        return [
            {
                "id": str(r.id),
                "title": r.merchant_raw or "",
                "amount": r.amount,
                "currency": r.currency.value if r.currency else "RUB",
                "due_date": r.occurred_at.date().isoformat(),
                "primary_tag": r.primary_tag,
                "direction": r.direction.value,
            }
            for r in rows
        ]

    # ─── Accounts ─────────────────────────────────────────────────────────────

    def get_or_create_default_account(self, household_id: str) -> Account:
        """Return (creating if needed) the default 'Наличные' RUB account."""
        import uuid as _u
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id
        acc = (
            self.db.query(Account)
            .filter(
                Account.household_id == hid,
                Account.name == "Наличные",
                Account.currency == Currency.RUB,
                Account.is_active.is_(True),
            )
            .first()
        )
        if acc is None:
            acc = Account(
                id=_u.uuid4(),
                household_id=hid,
                name="Наличные",
                currency=Currency.RUB,
                is_shared=True,
                is_active=True,
            )
            self.db.add(acc)
            self.db.flush()
        return acc

    def create_account(
        self,
        household_id: str,
        name: str,
        currency: Currency,
        owner_user_id: str | None = None,
        is_shared: bool = True,
    ) -> Account:
        import uuid as _u
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id
        acc = Account(
            id=_u.uuid4(),
            household_id=hid,
            owner_user_id=_uuid.UUID(owner_user_id) if owner_user_id else None,
            name=name,
            currency=currency,
            is_shared=is_shared,
            is_active=True,
        )
        self.db.add(acc)
        self.db.commit()
        return acc

    def update_balance_snapshot(
        self,
        account_id: str,
        household_id: str,
        new_balance: Decimal,
        user_id: str | None = None,
    ) -> tuple[BalanceSnapshot, Transaction | None]:
        """Save new balance snapshot; create a delta transaction visible in /inbox."""
        import uuid as _u
        aid = _uuid.UUID(account_id) if isinstance(account_id, str) else account_id
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id
        uid = _uuid.UUID(user_id) if user_id else None

        acc = self.db.query(Account).filter(Account.id == aid).first()
        prev = (
            self.db.query(BalanceSnapshot)
            .filter(BalanceSnapshot.account_id == aid)
            .order_by(BalanceSnapshot.created_at.desc())
            .first()
        )

        snapshot = BalanceSnapshot(
            id=_u.uuid4(),
            account_id=aid,
            household_id=hid,
            actual_balance=new_balance,
            created_by_user_id=uid,
        )
        self.db.add(snapshot)

        delta_tx = None
        if prev is not None:
            delta = new_balance - Decimal(str(prev.actual_balance))
            if delta != 0 and acc is not None:
                direction = TransactionDirection.INCOME if delta > 0 else TransactionDirection.EXPENSE
                delta_tx = Transaction(
                    id=_u.uuid4(),
                    household_id=hid,
                    user_id=uid,
                    account_id=aid,
                    direction=direction,
                    amount=abs(delta),
                    currency=acc.currency,
                    occurred_at=datetime.now(timezone.utc),
                    merchant_raw=f"Корректировка: {acc.name}",
                    source="telegram",
                    parse_status="ok",
                    primary_tag="корректировка",
                    extra_tags=[],
                )
                self.db.add(delta_tx)

        self.db.commit()
        return snapshot, delta_tx

    # ─── Account transaction history (running balance) ───────────────────────

    def get_account_history(self, account_id: str, limit: int = 10) -> dict[str, Any]:
        """Return last `limit` actual transactions after the latest BalanceSnapshot,
        with a running balance computed from the snapshot amount.

        Returns:
            {
              "snapshot": {"amount": Decimal, "date": str} | None,
              "transactions": [{"date": str, "merchant": str, "amount": Decimal,
                                "direction": str, "currency": str, "running_balance": Decimal}],
              "warning": str | None,
            }
        """
        aid = _uuid.UUID(account_id) if isinstance(account_id, str) else account_id

        snapshot = (
            self.db.query(BalanceSnapshot)
            .filter(BalanceSnapshot.account_id == aid)
            .order_by(BalanceSnapshot.created_at.desc())
            .first()
        )
        if snapshot is None:
            return {"snapshot": None, "transactions": [], "warning": "no_snapshot"}

        snap_amount = Decimal(str(snapshot.actual_balance))
        snap_date = snapshot.created_at

        txns = (
            self.db.query(Transaction)
            .filter(
                Transaction.account_id == aid,
                Transaction.is_planned.is_(False),
                Transaction.is_skipped.is_(False),
                Transaction.occurred_at > snap_date,
            )
            .order_by(Transaction.occurred_at.asc())
            .all()
        )

        running = snap_amount
        rows = []
        for tx in txns:
            amount = Decimal(str(tx.amount))
            direction = tx.direction.value if tx.direction else "expense"
            if direction == "income":
                running += amount
            elif direction == "expense":
                running -= amount
            rows.append({
                "date": tx.occurred_at.strftime("%d.%m"),
                "merchant": tx.merchant_raw or "—",
                "amount": amount,
                "direction": direction,
                "currency": tx.currency.value if tx.currency else "RUB",
                "running_balance": running,
            })

        # Return last `limit` rows
        rows = rows[-limit:]
        return {
            "snapshot": {
                "amount": snap_amount,
                "date": snap_date.strftime("%d.%m"),
            },
            "transactions": rows,
            "warning": None,
        }

    # ─── Balance summary for /month ──────────────────────────────────────────

    def balance_summary(self, household_id: str, for_date: date | None = None) -> dict[str, Any]:
        """Return per-account balance info: latest snapshot and start-of-month snapshot."""
        today = for_date or datetime.now(timezone.utc).date()
        month_start = today.replace(day=1)
        month_start_dt = datetime(month_start.year, month_start.month, month_start.day, tzinfo=timezone.utc)
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id

        accounts = (
            self.db.query(Account)
            .filter(Account.household_id == hid, Account.is_active.is_(True))
            .order_by(Account.created_at.asc())
            .all()
        )
        if not accounts:
            return {"accounts": [], "total_by_currency": {}}

        result = []
        total_by_currency: dict[str, Decimal] = {}
        for acc in accounts:
            # Latest snapshot (current balance)
            latest = (
                self.db.query(BalanceSnapshot)
                .filter(BalanceSnapshot.account_id == acc.id)
                .order_by(BalanceSnapshot.created_at.desc())
                .first()
            )
            # Snapshot closest to month start (for delta)
            month_start_snap = (
                self.db.query(BalanceSnapshot)
                .filter(
                    BalanceSnapshot.account_id == acc.id,
                    BalanceSnapshot.created_at < month_start_dt,
                )
                .order_by(BalanceSnapshot.created_at.desc())
                .first()
            )

            cur = acc.currency.value
            current_bal = Decimal(str(latest.actual_balance)) if latest else None
            start_bal = Decimal(str(month_start_snap.actual_balance)) if month_start_snap else None

            if current_bal is not None:
                total_by_currency[cur] = total_by_currency.get(cur, Decimal("0")) + current_bal

            result.append({
                "name": acc.name,
                "currency": cur,
                "current_balance": current_bal,
                "month_start_balance": start_bal,
                "delta": (current_bal - start_bal) if current_bal is not None and start_bal is not None else None,
            })

        return {"accounts": result, "total_by_currency": total_by_currency}

    # ─── Legacy: keep for existing API routes ─────────────────────────────────

    def upcoming_payments(self, household_id: str, days: int = 7, until_date: date | None = None) -> list[dict[str, Any]]:
        """Alias → upcoming_planned() for backward compatibility with API routes."""
        return self.upcoming_planned(household_id, days=days, until_date=until_date)
