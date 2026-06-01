from __future__ import annotations

import calendar
import uuid as _uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

# ЗАКОН: get_monthly_actual() фильтрует is_planned=False AND is_internal_transfer=False.
# get_planned_total() фильтрует is_planned=True AND occurred_at > now().
# Смешивать нельзя нигде. Проверяй каждый новый запрос.

from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import (
    Account,
    BalanceSnapshot,
    PlannedPayment,
    RawImportTransaction,
    Transaction,
    User,
)


# Data-health thresholds — tune here.
BAL_WARN_D = 7      # balance not verified for ≥ this many days → amber
BAL_ERR_D = 14      # → red (and "never verified" is always red)
IMPORT_WARN_D = 3   # no import from a source for ≥ this many days → amber
IMPORT_ERR_D = 7    # → red
UNCAT_RED_COUNT = 10  # more uncategorized than this → red
UNCAT_RED_AGE_D = 14  # oldest uncategorized older than this → red
UNCAT_ITEM_CAP = 50   # cap the inline list shown on the page


def _status_from_age(age_days: int | None, warn: int, err: int) -> str:
    if age_days is None:
        return "red"  # never recorded
    if age_days >= err:
        return "red"
    if age_days >= warn:
        return "amber"
    return "green"


def _signal_uncat_status(count: int, oldest_days: int | None) -> str:
    if count == 0:
        return "green"
    if count > UNCAT_RED_COUNT or (oldest_days is not None and oldest_days > UNCAT_RED_AGE_D):
        return "red"
    return "amber"


def _worst(statuses: list[str]) -> str:
    if "red" in statuses:
        return "red"
    if "amber" in statuses:
        return "amber"
    return "green"


DRIFT_EPS = 0.01  # |drift| at or below this is treated as fully reconciled


def _drift_status(drift: float | None) -> str:
    """Reconciliation status from the unexplained balance drift.

    None (fewer than two snapshots → nothing to reconcile yet) and a near-zero
    drift are both green; any other unexplained difference is amber.
    """
    if drift is None:
        return "green"
    return "green" if abs(drift) <= DRIFT_EPS else "amber"


# ─── REST-mode FX helpers (per-date conversion) ──────────────────────────────
# Used by the *_via_rest service methods. Mirror fx_service.convert_to_rub
# semantics (date-aware, 7-day backward fallback) but operate over
# bulk-fetched fx_rates rows instead of a SQLAlchemy session.

def _build_fx_lookup(fx_rows: list[dict]) -> dict[str, list[tuple[str, float]]]:
    """{currency_lower -> [(date_str, rate), …]} sorted by date desc per currency."""
    by_cur: dict[str, list[tuple[str, float]]] = {}
    for r in fx_rows:
        cur = (r.get("from_currency") or "").lower()
        if not cur:
            continue
        by_cur.setdefault(cur, []).append(((r.get("date") or "")[:10], float(r["rate"])))
    for k in by_cur:
        by_cur[k].sort(key=lambda x: x[0], reverse=True)
    return by_cur


def _rub_on_date(
    amount: float,
    currency: str | None,
    occurred_date: str | None,
    fx_by_cur: dict[str, list[tuple[str, float]]],
) -> float:
    """Convert amount to RUB using the fx_rate on/before occurred_date (7-day fallback).

    Falls back to 1.0 if no rate found within 7 days; same silent behaviour as the
    previous latest-only lookup. Missing-rate cells should be backfilled separately.
    """
    cur = (currency or "rub").lower()
    if cur == "rub":
        return amount
    if cur == "usdt":
        cur = "usd"
    rates = fx_by_cur.get(cur, [])
    d_iso = (occurred_date or "")[:10]
    if not d_iso:
        return amount * rates[0][1] if rates else amount
    try:
        d = date.fromisoformat(d_iso)
    except ValueError:
        # Unparseable date → can't do a meaningful per-date lookup. Silent 1:1.
        return amount
    cutoff = (d - timedelta(days=7)).isoformat()
    for row_date, rate in rates:
        if cutoff <= row_date <= d_iso:
            return amount * rate
    return amount  # silent 1:1; backfill fx_rates if this matters


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
                Transaction.is_internal_transfer == False,  # noqa: E712 — ЗАКОН: no internal transfers
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

        upcoming = self.upcoming_transactions(household_id, until_date=month_end)

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
                Transaction.is_internal_transfer == False,  # noqa: E712 — ЗАКОН: no internal transfers
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

        planned_soon = self.upcoming_transactions(household_id, until_date=soon_until)

        return {
            "spend_by_currency": spend_by_currency,
            "income_by_currency": income_by_currency,
            "planned_soon": planned_soon,
            "untagged_count": untagged_count,
        }

    # ─── Planned totals (is_planned=True) ────────────────────────────────────

    def get_planned_total(self, household_id: str, year: int, month: int) -> dict[str, Any]:
        """Sum of planned (is_planned=True) future transactions for the month, by direction.

        ЗАКОН: фильтр is_planned=True AND occurred_at > now().
        Returns {"expense_by_currency": {...}, "income_by_currency": {...}}.
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
                Transaction.is_skipped.is_(False),
            )
            .all()
        )

        expense_totals: dict[str, Decimal] = {}
        income_totals: dict[str, Decimal] = {}
        for tx in rows:
            cur = tx.currency.value if tx.currency else "RUB"
            amount = Decimal(str(tx.amount))
            if tx.direction == TransactionDirection.EXPENSE:
                expense_totals[cur] = expense_totals.get(cur, Decimal("0")) + amount
            elif tx.direction == TransactionDirection.INCOME:
                income_totals[cur] = income_totals.get(cur, Decimal("0")) + amount
        return {"expense_by_currency": expense_totals, "income_by_currency": income_totals}

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

    def upcoming_transactions(self, household_id: str, until_date: date | None = None) -> list[dict[str, Any]]:
        """Planned transactions not yet skipped: is_planned=True, is_skipped=False, occurred_at > now."""
        today = datetime.now(timezone.utc).date()
        tomorrow_dt = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) + timedelta(days=1)
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id

        filters = [
            Transaction.household_id == hid,
            Transaction.is_planned.is_(True),
            Transaction.is_skipped.is_(False),
            Transaction.occurred_at >= tomorrow_dt,
            Transaction.direction != TransactionDirection.TRANSFER,
            Transaction.direction != TransactionDirection.EXCHANGE,
        ]
        if until_date is not None:
            until_dt = datetime(until_date.year, until_date.month, until_date.day, 23, 59, 59, tzinfo=timezone.utc)
            filters.append(Transaction.occurred_at <= until_dt)

        rows = (
            self.db.query(Transaction)
            .filter(*filters)
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
    ) -> tuple[BalanceSnapshot, None]:
        """Save a new balance snapshot.

        Records only the snapshot. The discrepancy versus the balance implied by
        transactions is derived on the fly as reconciliation drift in
        data_health() — we no longer mint a fixed «корректировка» transaction
        (it never updated when a past-dated expense was added later). The second
        tuple element stays for backward compatibility and is always None.
        """
        import uuid as _u
        aid = _uuid.UUID(account_id) if isinstance(account_id, str) else account_id
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id
        uid = _uuid.UUID(user_id) if user_id else None

        snapshot = BalanceSnapshot(
            id=_u.uuid4(),
            account_id=aid,
            household_id=hid,
            actual_balance=new_balance,
            created_by_user_id=uid,
        )
        self.db.add(snapshot)
        self.db.commit()
        return snapshot, None

    # ─── Web transaction create / edit ───────────────────────────────────────

    @staticmethod
    def _clean_tag(tag: str | None) -> str | None:
        """Normalize a user-entered tag: strip, drop a leading '#', lowercase.
        Empty → None. Matches how the bot stores tags (TagBudget matching)."""
        if tag is None:
            return None
        t = tag.strip().lstrip("#").strip().lower()
        return t or None

    @staticmethod
    def _web_fingerprint(household_id, amount, currency, merchant, tx_date, direction) -> str:
        import hashlib
        payload = (
            f"{household_id}|{tx_date}|{amount}|{currency}|"
            f"{(merchant or '').strip().lower()}|{direction}|web"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _as_datetime(value) -> datetime:
        """Coerce a date/datetime/ISO string to a tz-aware UTC datetime."""
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def create_transaction(
        self,
        *,
        household_id: str,
        amount: Decimal,
        currency,
        direction,
        occurred_at,
        primary_tag: str | None = None,
        account_id: str | None = None,
        merchant: str | None = None,
        user_id: str | None = None,
        is_planned: bool = False,
    ) -> Transaction:
        """Create a transaction from the web UI (source='web'). Computes a
        dedup_fingerprint with the 'web' source suffix."""
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id
        cur = Currency(currency) if not isinstance(currency, Currency) else currency
        dir_ = (
            TransactionDirection(direction)
            if not isinstance(direction, TransactionDirection)
            else direction
        )
        occ = self._as_datetime(occurred_at)
        tag = self._clean_tag(primary_tag)
        fp = self._web_fingerprint(hid, amount, cur.value, merchant, occ.date().isoformat(), dir_.value)

        tx = Transaction(
            id=_uuid.uuid4(),
            household_id=hid,
            user_id=_uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
            account_id=_uuid.UUID(account_id) if isinstance(account_id, str) else account_id,
            direction=dir_,
            amount=amount,
            currency=cur,
            occurred_at=occ,
            merchant_raw=merchant,
            source="web",
            parse_status="ok",
            primary_tag=tag,
            extra_tags=[],
            is_planned=is_planned,
            is_internal_transfer=False,
            is_skipped=False,
            dedup_fingerprint=fp,
        )
        self.db.add(tx)
        self.db.commit()
        return tx

    def update_transaction(self, tx_id: str, **fields) -> Transaction | None:
        """Update editable fields of a transaction. Recognized keys: amount,
        currency, direction, occurred_at, primary_tag, account_id, merchant.
        Returns the row, or None if not found. Unknown keys are ignored;
        omitted keys are left unchanged."""
        try:
            tid = _uuid.UUID(tx_id) if isinstance(tx_id, str) else tx_id
        except ValueError:
            return None
        tx = self.db.get(Transaction, tid)
        if tx is None:
            return None
        if "amount" in fields and fields["amount"] is not None:
            tx.amount = fields["amount"]
        if "currency" in fields and fields["currency"] is not None:
            tx.currency = Currency(fields["currency"]) if not isinstance(fields["currency"], Currency) else fields["currency"]
        if "direction" in fields and fields["direction"] is not None:
            tx.direction = (
                TransactionDirection(fields["direction"])
                if not isinstance(fields["direction"], TransactionDirection)
                else fields["direction"]
            )
        if "occurred_at" in fields and fields["occurred_at"] is not None:
            tx.occurred_at = self._as_datetime(fields["occurred_at"])
        if "primary_tag" in fields:
            tx.primary_tag = self._clean_tag(fields["primary_tag"])
        if "account_id" in fields and fields["account_id"] is not None:
            aid = fields["account_id"]
            tx.account_id = _uuid.UUID(aid) if isinstance(aid, str) else aid
        if "merchant" in fields and fields["merchant"] is not None:
            tx.merchant_raw = fields["merchant"]
        self.db.commit()
        return tx

    def upsert_tag_budget(
        self,
        household_id: str,
        month_key: str,
        tag: str,
        limit_amount: Decimal,
        currency: str = "RUB",
        rollover_enabled: bool | None = None,
    ) -> "TagBudget":
        """Create or update a per-tag monthly budget limit (web budget UI).
        Unique on (household_id, month_key, tag)."""
        from app.infrastructure.db.models import TagBudget

        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id
        norm_tag = self._clean_tag(tag) or ""
        row = (
            self.db.query(TagBudget)
            .filter(
                TagBudget.household_id == hid,
                TagBudget.month_key == month_key,
                TagBudget.tag == norm_tag,
            )
            .first()
        )
        if row is None:
            row = TagBudget(
                id=_uuid.uuid4(),
                household_id=hid,
                month_key=month_key,
                tag=norm_tag,
                limit_amount=limit_amount,
                currency=currency,
                rollover_enabled=bool(rollover_enabled),
            )
            self.db.add(row)
        else:
            row.limit_amount = limit_amount
            row.currency = currency
            if rollover_enabled is not None:
                row.rollover_enabled = rollover_enabled
        self.db.commit()
        return row

    # ─── Account transaction history (running balance) ───────────────────────

    def get_account_history(self, account_id: str, limit: int = 10) -> dict[str, Any]:
        """Return last `limit` actual transactions with a running balance.

        If no snapshot exists: running_start=0, fetches all transactions for the account.
        If no transactions are linked by account_id: falls back to household transactions
        for the last 30 days (temporary until account_id backfill is complete).

        Returns:
            {
              "snapshot": {"amount": Decimal, "date": str} | None,
              "transactions": [{"date": str, "merchant": str, "amount": Decimal,
                                "direction": str, "currency": str, "running_balance": Decimal}],
              "warning": str | None,
            }
        """
        aid = _uuid.UUID(account_id) if isinstance(account_id, str) else account_id

        account = self.db.query(Account).filter(Account.id == aid).first()

        snapshot = (
            self.db.query(BalanceSnapshot)
            .filter(BalanceSnapshot.account_id == aid)
            .order_by(BalanceSnapshot.created_at.desc())
            .first()
        )

        warning: str | None = None
        if snapshot is None:
            snap_amount = Decimal("0")
            warning = "no_snapshot"
            # Fetch all transactions linked to this account
            txns = (
                self.db.query(Transaction)
                .filter(
                    Transaction.account_id == aid,
                    Transaction.is_planned.is_(False),
                    Transaction.is_skipped.is_(False),
                )
                .order_by(Transaction.occurred_at.asc())
                .all()
            )
            # Fallback: if account_id not backfilled, use household transactions (last 30 days)
            if not txns and account is not None:
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                txns = (
                    self.db.query(Transaction)
                    .filter(
                        Transaction.household_id == account.household_id,
                        Transaction.is_planned.is_(False),
                        Transaction.is_skipped.is_(False),
                        Transaction.occurred_at >= cutoff,
                    )
                    .order_by(Transaction.occurred_at.asc())
                    .all()
                )
                if txns:
                    warning = "no_snapshot_household_fallback"
        else:
            snap_amount = Decimal(str(snapshot.actual_balance))
            txns = (
                self.db.query(Transaction)
                .filter(
                    Transaction.account_id == aid,
                    Transaction.is_planned.is_(False),
                    Transaction.is_skipped.is_(False),
                    Transaction.occurred_at > snapshot.created_at,
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
                "date": snapshot.created_at.strftime("%d.%m"),
            } if snapshot else None,
            "transactions": rows,
            "warning": warning,
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

    def net_worth_rub(self, household_id: str, for_date: date | None = None) -> dict[str, Any]:
        """Total net worth in RUB, valuing each account's latest snapshot at the
        *real* applied exchange rate (valuation_rate_to_rub), CBR as fallback.

        Returns ``{"total_rub", "any_unavailable", "accounts": [...]}``. Accounts
        without a snapshot are skipped; a currency with no rate at all sets
        ``any_unavailable`` and is omitted from the total.
        """
        from app.application.services.fx_service import valuation_rate_to_rub

        today = for_date or datetime.now(timezone.utc).date()
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id

        accounts = (
            self.db.query(Account)
            .filter(Account.household_id == hid, Account.is_active.is_(True))
            .order_by(Account.created_at.asc())
            .all()
        )

        total = Decimal("0")
        any_unavailable = False
        cards: list[dict[str, Any]] = []
        for acc in accounts:
            latest = (
                self.db.query(BalanceSnapshot)
                .filter(BalanceSnapshot.account_id == acc.id)
                .order_by(BalanceSnapshot.created_at.desc())
                .first()
            )
            if latest is None:
                continue
            native = Decimal(str(latest.actual_balance))
            rate, source = valuation_rate_to_rub(hid, acc.currency.value, today, self.db)
            rub = (native * rate).quantize(Decimal("0.01")) if rate is not None else None
            if rub is None:
                any_unavailable = True
            else:
                total += rub
            cards.append({
                "name": acc.name,
                "currency": acc.currency.value,
                "native_balance": native,
                "rub": rub,
                "rate_source": source,
            })

        return {"total_rub": total, "any_unavailable": any_unavailable, "accounts": cards}

    # ─── Cashflow projection ──────────────────────────────────────────────────

    def cashflow_projection(self, household_id: str, days: int = 60) -> dict[str, Any]:
        """Return a cashflow projection over the next `days` days.

        Balances from latest BalanceSnapshot per account.
        Planned items from Transaction(is_planned=True).
        Debts from Debt(settled_at IS NULL, due_date in window) — info only, not in formula.
        Formula: free_balance = total_balances_rub - planned_expenses_rub + planned_income_rub.
        """
        from app.application.services.fx_service import convert_to_rub
        from app.infrastructure.db.models import Debt

        today = datetime.now(timezone.utc).date()
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id
        until_date = today + timedelta(days=days)
        cutoff_30 = today + timedelta(days=30)

        # 1. Account balances (latest snapshot per active account)
        accounts = (
            self.db.query(Account)
            .filter(Account.household_id == hid, Account.is_active.is_(True))
            .order_by(Account.created_at.asc())
            .all()
        )
        account_items: list[dict[str, Any]] = []
        balances_by_currency: dict[str, Decimal] = {}
        for acc in accounts:
            snap = (
                self.db.query(BalanceSnapshot)
                .filter(BalanceSnapshot.account_id == acc.id)
                .order_by(BalanceSnapshot.created_at.desc())
                .first()
            )
            cur = acc.currency.value
            if snap:
                bal = Decimal(str(snap.actual_balance))
                account_items.append({"name": acc.name, "currency": cur, "balance": bal})
                balances_by_currency[cur] = balances_by_currency.get(cur, Decimal("0")) + bal
            else:
                account_items.append({"name": acc.name, "currency": cur, "balance": None})

        # 2. Planned income/expenses in window
        planned = self.upcoming_transactions(household_id, until_date=until_date)
        planned_income = [p for p in planned if p["direction"] == "income"]
        planned_expenses = [p for p in planned if p["direction"] == "expense"]

        # 3. Debts due in window (info only)
        debt_rows = (
            self.db.query(Debt)
            .filter(
                Debt.household_id == hid,
                Debt.settled_at.is_(None),
                Debt.due_date.isnot(None),
                Debt.due_date >= today,
                Debt.due_date <= until_date,
            )
            .order_by(Debt.due_date.asc())
            .all()
        )
        debts_due = [
            {
                "due_date": d.due_date.isoformat(),
                "counterparty": d.counterparty_name,
                "amount": Decimal(str(d.amount)),
                "currency": d.currency,
                "direction": d.direction,
            }
            for d in debt_rows
        ]

        # 4. Convert to RUB for projections
        fx_unavailable = False

        total_balance_rub = Decimal("0")
        for cur, bal in balances_by_currency.items():
            rub = convert_to_rub(bal, cur, today, self.db)
            if rub is None:
                fx_unavailable = True
            else:
                total_balance_rub += rub

        income_30_rub = Decimal("0")
        income_60_rub = Decimal("0")
        expense_30_rub = Decimal("0")
        expense_60_rub = Decimal("0")

        for item in planned_income:
            rub = convert_to_rub(Decimal(str(item["amount"])), item["currency"], today, self.db)
            if rub is None:
                fx_unavailable = True
                rub = Decimal("0")
            income_60_rub += rub
            if item["due_date"] <= cutoff_30.isoformat():
                income_30_rub += rub

        for item in planned_expenses:
            rub = convert_to_rub(Decimal(str(item["amount"])), item["currency"], today, self.db)
            if rub is None:
                fx_unavailable = True
                rub = Decimal("0")
            expense_60_rub += rub
            if item["due_date"] <= cutoff_30.isoformat():
                expense_30_rub += rub

        return {
            "today": today,
            "days": days,
            "account_items": account_items,
            "balances_by_currency": balances_by_currency,
            "total_balance_rub": total_balance_rub,
            "planned_income": planned_income,
            "planned_expenses": planned_expenses,
            "debts_due": debts_due,
            "free_30": total_balance_rub - expense_30_rub + income_30_rub,
            "free_60": total_balance_rub - expense_60_rub + income_60_rub,
            "fx_unavailable": fx_unavailable,
        }

    # ─── Monthly report (UI) ─────────────────────────────────────────────────

    def monthly_report(self, household_id: str, year: int, month: int) -> dict[str, Any]:
        """Return all data needed by the monthly report UI.

        Includes both planned and actual transactions (ЗАКОН filters applied).
        Running balance is computed client-side from this data + snapshots.
        """
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id
        last_day = calendar.monthrange(year, month)[1]
        start_dt = datetime(year, month, 1, tzinfo=timezone.utc)
        end_dt = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)

        accounts = (
            self.db.query(Account)
            .filter(Account.household_id == hid, Account.is_active.is_(True))
            .all()
        )

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

        snapshots: dict[str, dict | None] = {}
        latest_snapshots: dict[str, dict | None] = {}
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
            latest = (
                self.db.query(BalanceSnapshot)
                .filter(BalanceSnapshot.account_id == acc.id)
                .order_by(BalanceSnapshot.created_at.desc())
                .first()
            )
            latest_snapshots[str(acc.id)] = (
                {
                    "actual_balance": float(latest.actual_balance),
                    "as_of": latest.created_at.date().isoformat(),
                }
                if latest else None
            )

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
            "latest_snapshots": latest_snapshots,
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

    def monthly_report_via_rest(self, household_id: str, year: int, month: int) -> dict[str, Any]:
        """REST-API variant of monthly_report. Talks to PostgREST via SupabaseClient
        instead of opening a Postgres socket. Same return shape as monthly_report().
        """
        from app.infrastructure.config.settings import get_settings
        from app.infrastructure.supabase import SupabaseClient

        settings = get_settings()
        last_day = calendar.monthrange(year, month)[1]
        start_dt = datetime(year, month, 1, tzinfo=timezone.utc)
        end_dt = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()

        with SupabaseClient(settings.supabase_url, settings.supabase_service_role_key) as sb:
            accounts = sb.get("accounts", {
                "select": "id,name,currency,is_active",
                "household_id": f"eq.{household_id}",
                "is_active": "eq.true",
            })

            txs = sb.get("transactions", {
                "select": "id,occurred_at,direction,amount,currency,merchant_raw,primary_tag,account_id,is_planned,is_internal_transfer,is_skipped",
                "household_id": f"eq.{household_id}",
                "occurred_at": [f"gte.{start_iso}", f"lte.{end_iso}"],
                "is_internal_transfer": "eq.false",
                "is_skipped": "eq.false",
                "direction": "neq.exchange",
                "order": "occurred_at.asc",
            })

            # Bulk-fetch latest snapshot per account in a single REST call.
            # Include snapshots dated within the first day of the viewed month (snapshot
            # at "April 1 09:24" should anchor the April view, not just May+ views).
            from datetime import timedelta
            snap_cutoff = (start_dt + timedelta(days=1)).isoformat()
            snapshots: dict[str, dict | None] = {a["id"]: None for a in accounts}
            latest_snapshots: dict[str, dict | None] = {a["id"]: None for a in accounts}
            account_ids = [a["id"] for a in accounts]
            if account_ids:
                snap_rows = sb.get("balance_snapshots", {
                    "select": "account_id,actual_balance,created_at",
                    "account_id": f"in.({','.join(account_ids)})",
                    "created_at": f"lt.{snap_cutoff}",
                    "order": "account_id.asc,created_at.desc",
                })
                for r in snap_rows:
                    aid = r["account_id"]
                    if snapshots.get(aid) is None:
                        snapshots[aid] = {
                            "actual_balance": float(r["actual_balance"]),
                            "as_of": (r.get("created_at") or "")[:10],
                        }
                # Latest snapshot regardless of date (for the "current balance" header)
                latest_rows = sb.get("balance_snapshots", {
                    "select": "account_id,actual_balance,created_at",
                    "account_id": f"in.({','.join(account_ids)})",
                    "order": "account_id.asc,created_at.desc",
                })
                for r in latest_rows:
                    aid = r["account_id"]
                    if latest_snapshots.get(aid) is None:
                        latest_snapshots[aid] = {
                            "actual_balance": float(r["actual_balance"]),
                            "as_of": (r.get("created_at") or "")[:10],
                        }

            # FX rates: pull a window covering the viewed month + a 14-day backward
            # buffer (so the per-date helper's 7-day fallback always has data even
            # near the window's left edge). Also include rows up to today, since the
            # account-card "latest_snapshots" convert at the most-recent snapshot
            # date, which can be after end_dt of the viewed month.
            fx_window_start = (start_dt - timedelta(days=14)).date().isoformat()
            today_iso_d = date.today().isoformat()
            fx_rows = sb.get("fx_rates", {
                "select": "from_currency,rate,date",
                "to_currency": "eq.RUB",
                "date": [f"gte.{fx_window_start}", f"lte.{today_iso_d}"],
                "order": "date.desc",
            })
            fx_by_cur = _build_fx_lookup(fx_rows)
            # Latest-per-currency view (kept for frontend payload compat).
            fx_latest: dict[str, float] = {cur: rows[0][1] for cur, rows in fx_by_cur.items() if rows}

        today = date.today()
        tag_map: dict[str, float] = {}
        out_txs: list[dict[str, Any]] = []
        for tx in txs:
            occurred_str = (tx["occurred_at"] or "")[:10]
            try:
                occurred = date.fromisoformat(occurred_str)
            except ValueError:
                occurred = today

            if tx["is_planned"]:
                status = "overdue" if occurred <= today else "planned"
            elif "[сюрприз]" in (tx.get("merchant_raw") or "").lower() or "[surprise]" in (tx.get("merchant_raw") or "").lower():
                status = "unplanned"
            else:
                status = "actual"

            if not tx["is_planned"] and tx["direction"] == "expense":
                tag = tx.get("primary_tag") or "(без тега)"
                tag_map[tag] = tag_map.get(tag, 0.0) + float(tx["amount"])

            out_txs.append({
                "id": tx["id"],
                "occurred_at": occurred_str,
                "direction": tx["direction"],
                "amount": float(tx["amount"]),
                "currency": tx.get("currency") or "rub",
                "merchant_raw": tx.get("merchant_raw") or "",
                "primary_tag": tx.get("primary_tag"),
                "account_id": tx.get("account_id"),
                "is_planned": tx["is_planned"],
                "is_internal_transfer": tx["is_internal_transfer"],
                "status": status,
            })

        tag_summary = [
            {"tag": t, "total_rub": v}
            for t, v in sorted(tag_map.items(), key=lambda x: -x[1])
        ]

        # Server-side balance computation (so frontend doesn't redo FX/snapshot math)
        today_d = today
        is_current = (year == today_d.year and month == today_d.month)
        today_iso = today_d.isoformat()

        # Anchor-snapshot RUB conversion uses the snapshot's own date.
        total_start_rub = 0.0
        for a in accounts:
            snap = snapshots.get(a["id"])
            if not snap:
                continue
            total_start_rub += _rub_on_date(
                snap["actual_balance"], a.get("currency"), snap.get("as_of"), fx_by_cur,
            )

        # Transaction deltas: each converts at its own occurred_at date.
        # delta_rub: actual income/expense up to today (current view) or for the whole
        #            month (past/future views).
        # forecast_planned_rub: planned-not-yet-actual income/expense, used for the
        #            EOM forecast in current+future views; ignored for past views.
        is_future = (year > today_d.year) or (year == today_d.year and month > today_d.month)
        delta_rub = 0.0
        forecast_planned_rub = 0.0
        for tx in txs:
            if tx.get("is_internal_transfer"):
                continue
            if tx.get("direction") == "exchange":
                continue
            occ = (tx.get("occurred_at") or "")[:10]
            sign = 1 if tx.get("direction") == "income" else (-1 if tx.get("direction") == "expense" else 0)
            if sign == 0:
                continue
            rub = _rub_on_date(float(tx["amount"]), tx.get("currency"), occ, fx_by_cur)
            if tx.get("is_planned"):
                # Current or future month: planned rows belong to EOM forecast,
                # regardless of whether occurred_at is before or after today.
                # Overdue planned (occ <= today in current view) is still expected
                # to happen this month; it just hasn't materialised yet.
                # Past months: planned rows ignored — what didn't happen didn't happen.
                if is_current or is_future:
                    forecast_planned_rub += sign * rub
                continue
            if is_current and occ > today_iso:
                continue
            delta_rub += sign * rub

        balance_value_rub = total_start_rub + delta_rub
        # EOM forecast: only meaningful for current or future months.
        forecast_eom_rub = balance_value_rub + forecast_planned_rub if (is_current or is_future) else balance_value_rub

        # Per-account RUB balance computed at the LATEST snapshot's own date.
        # Single source of truth for the dashboard account cards — frontend renders
        # this directly instead of calling toRub() with today's FX (which produced
        # silent drift whenever FX moved between the snapshot date and today).
        account_payload = []
        for a in accounts:
            latest = latest_snapshots.get(a["id"]) or {}
            native = latest.get("actual_balance")
            balance_rub = (
                _rub_on_date(float(native), a.get("currency"), latest.get("as_of"), fx_by_cur)
                if native is not None else None
            )
            account_payload.append({
                "id": a["id"],
                "name": a["name"],
                "currency": a["currency"],
                "balance_native": float(native) if native is not None else None,
                "balance_rub": balance_rub,
                "balance_as_of": latest.get("as_of"),
            })

        return {
            "year": year,
            "month": month,
            "household_id": household_id,
            "is_current_month": is_current,
            "balance_value_rub": balance_value_rub,
            "start_balance_rub": total_start_rub,
            "forecast_eom_rub": forecast_eom_rub,
            "accounts": account_payload,
            "snapshots": snapshots,
            "latest_snapshots": latest_snapshots,
            "transactions": out_txs,
            "tag_summary": tag_summary,
            "fx_rates": fx_latest,
        }

    # ─── Cashflow monthly aggregate (Cashflow tab) ────────────────────────────

    def cashflow_monthly(
        self,
        household_id: str,
        start_month: date,
        end_month: date,
    ) -> dict[str, Any]:
        """Monthly cashflow aggregate for the dashboard Cashflow tab.

        Splits planned items into liquid vs tmcc-funded buckets, tracks tmcc
        grace payments as principal (net-wealth-neutral), and produces per-month
        running net wealth = liquid_assets - tmcc_liability. Forecast only —
        planned rows; actuals are not included here.
        """
        from app.application.services.fx_service import convert_to_rub

        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id
        today = datetime.now(timezone.utc).date()

        accounts = (
            self.db.query(Account)
            .filter(Account.household_id == hid, Account.is_active.is_(True))
            .all()
        )
        tmcc_acc = next((a for a in accounts if a.name.lower() == "tmcc"), None)
        tmcc_id = tmcc_acc.id if tmcc_acc else None

        # Starting position: liquid = latest snapshot per active non-tmcc account,
        # tmcc_liability = -(latest tmcc snapshot if any, else 0). All FX → RUB.
        liquid_rub = Decimal("0")
        tmcc_liab_rub = Decimal("0")
        as_of: date | None = None
        for acc in accounts:
            snap = (
                self.db.query(BalanceSnapshot)
                .filter(BalanceSnapshot.account_id == acc.id)
                .order_by(BalanceSnapshot.created_at.desc())
                .first()
            )
            if snap is None:
                continue
            bal = Decimal(str(snap.actual_balance))
            rub = convert_to_rub(bal, acc.currency.value, today, self.db) or bal
            if as_of is None or snap.created_at.date() > as_of:
                as_of = snap.created_at.date()
            if tmcc_id is not None and acc.id == tmcc_id:
                # tmcc snapshot is stored as a negative balance → liability is its abs
                tmcc_liab_rub += -rub
            else:
                liquid_rub += rub

        # Window: include the full last month
        last_day = calendar.monthrange(end_month.year, end_month.month)[1]
        window_start_dt = datetime(start_month.year, start_month.month, 1, tzinfo=timezone.utc)
        window_end_dt = datetime(end_month.year, end_month.month, last_day, 23, 59, 59, tzinfo=timezone.utc)

        # Pull all planned rows in the window in one query.
        txs = (
            self.db.query(Transaction)
            .filter(
                Transaction.household_id == hid,
                Transaction.is_planned.is_(True),
                Transaction.is_skipped.is_(False),
                Transaction.is_internal_transfer.is_(False),
                Transaction.direction.in_([TransactionDirection.INCOME, TransactionDirection.EXPENSE]),
                Transaction.occurred_at >= window_start_dt,
                Transaction.occurred_at <= window_end_dt,
            )
            .order_by(Transaction.occurred_at.asc())
            .all()
        )

        # Bucket each row + compute RUB equivalent
        def _month_key(dt: datetime) -> str:
            return f"{dt.year:04d}-{dt.month:02d}"

        # Iterate forward, accumulating end-of-month liquid + tmcc liab.
        running_liquid = liquid_rub
        running_tmcc_liab = tmcc_liab_rub

        months_out: list[dict[str, Any]] = []
        # Iterate calendar months inclusive
        cur_year, cur_month = start_month.year, start_month.month
        while True:
            cur_key = f"{cur_year:04d}-{cur_month:02d}"
            month_first = date(cur_year, cur_month, 1)
            month_last = date(cur_year, cur_month, calendar.monthrange(cur_year, cur_month)[1])

            income_rub = Decimal("0")
            expense_liquid_rub = Decimal("0")
            expense_tmcc_rub = Decimal("0")
            tmcc_grace_rub = Decimal("0")
            line_items: list[dict[str, Any]] = []

            for tx in txs:
                tx_d = tx.occurred_at.date()
                if tx_d < month_first or tx_d > month_last:
                    continue
                cur = tx.currency.value if tx.currency else "rub"
                amt = Decimal(str(tx.amount))
                rub = convert_to_rub(amt, cur, tx_d, self.db) or amt

                is_tmcc_funded = (tmcc_id is not None and tx.account_id == tmcc_id)
                desc = (tx.description or "")
                tag = tx.primary_tag or ""
                is_grace_pmt = (
                    tx.direction == TransactionDirection.EXPENSE
                    and not is_tmcc_funded
                    and tag == "debt_repayment"
                    and "tmcc" in desc.lower()
                )

                if tx.direction == TransactionDirection.INCOME:
                    income_rub += rub
                    bucket = "liquid"
                elif is_tmcc_funded:
                    expense_tmcc_rub += rub
                    bucket = "tmcc"
                else:
                    expense_liquid_rub += rub
                    if is_grace_pmt:
                        tmcc_grace_rub += rub
                    bucket = "liquid"

                line_items.append({
                    "date": tx_d.isoformat(),
                    "direction": tx.direction.value,
                    "amount": float(amt),
                    "currency": cur,
                    "rub_equiv": float(rub),
                    "primary_tag": tx.primary_tag,
                    "description": tx.description,
                    "bucket": bucket,
                })

            delta_liquid = income_rub - expense_liquid_rub
            running_liquid = running_liquid + delta_liquid
            # tmcc liability: grace payments reduce it, new tmcc charges increase it
            running_tmcc_liab = running_tmcc_liab - tmcc_grace_rub + expense_tmcc_rub
            end_net_wealth = running_liquid - running_tmcc_liab

            months_out.append({
                "month": cur_key,
                "income_rub": float(income_rub),
                "expense_liquid_rub": float(expense_liquid_rub),
                "expense_tmcc_rub": float(expense_tmcc_rub),
                "tmcc_grace_payments_rub": float(tmcc_grace_rub),
                "delta_liquid_rub": float(delta_liquid),
                "end_liquid_rub": float(running_liquid),
                "end_tmcc_liab_rub": float(running_tmcc_liab),
                "end_net_wealth_rub": float(end_net_wealth),
                "line_items": line_items,
            })

            if cur_year == end_month.year and cur_month == end_month.month:
                break
            cur_month += 1
            if cur_month > 12:
                cur_month = 1
                cur_year += 1

        return {
            "window": {
                "start": f"{start_month.year:04d}-{start_month.month:02d}",
                "end": f"{end_month.year:04d}-{end_month.month:02d}",
            },
            "starting_position": {
                "liquid_rub": float(liquid_rub),
                "tmcc_liability_rub": float(tmcc_liab_rub),
                "net_wealth_rub": float(liquid_rub - tmcc_liab_rub),
                "as_of": as_of.isoformat() if as_of else None,
            },
            "months": months_out,
        }

    def cashflow_monthly_via_rest(
        self,
        household_id: str,
        start_month: date,
        end_month: date,
    ) -> dict[str, Any]:
        """REST-API variant of cashflow_monthly. Same return shape — used on Vercel
        where the direct Postgres socket is unreliable."""
        from app.infrastructure.config.settings import get_settings
        from app.infrastructure.supabase import SupabaseClient

        settings = get_settings()

        last_day = calendar.monthrange(end_month.year, end_month.month)[1]
        window_start_dt = datetime(start_month.year, start_month.month, 1, tzinfo=timezone.utc)
        window_end_dt = datetime(end_month.year, end_month.month, last_day, 23, 59, 59, tzinfo=timezone.utc)
        window_start_iso = window_start_dt.isoformat()
        window_end_iso = window_end_dt.isoformat()

        with SupabaseClient(settings.supabase_url, settings.supabase_service_role_key) as sb:
            accounts = sb.get("accounts", {
                "select": "id,name,currency,is_active",
                "household_id": f"eq.{household_id}",
                "is_active": "eq.true",
            })

            account_ids = [a["id"] for a in accounts]
            latest_snap: dict[str, dict | None] = {aid: None for aid in account_ids}
            if account_ids:
                snap_rows = sb.get("balance_snapshots", {
                    "select": "account_id,actual_balance,created_at",
                    "account_id": f"in.({','.join(account_ids)})",
                    "order": "account_id.asc,created_at.desc",
                })
                for r in snap_rows:
                    aid = r["account_id"]
                    if latest_snap.get(aid) is None:
                        latest_snap[aid] = r

            txs = sb.get("transactions", {
                "select": "id,occurred_at,direction,amount,currency,description,primary_tag,account_id,is_planned,is_internal_transfer,is_skipped",
                "household_id": f"eq.{household_id}",
                "is_planned": "eq.true",
                "is_skipped": "eq.false",
                "is_internal_transfer": "eq.false",
                "direction": "in.(income,expense)",
                "occurred_at": [f"gte.{window_start_iso}", f"lte.{window_end_iso}"],
                "order": "occurred_at.asc",
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

        def to_rub(amount: Decimal, currency: str) -> Decimal:
            cur = (currency or "rub").lower()
            if cur == "rub":
                return amount
            rate = fx_latest.get(cur)
            if rate is None and cur == "usdt":
                rate = fx_latest.get("usd")
            if rate is None:
                return amount
            return amount * Decimal(str(rate))

        tmcc_acc = next((a for a in accounts if (a.get("name") or "").lower() == "tmcc"), None)
        tmcc_id = tmcc_acc["id"] if tmcc_acc else None

        liquid_rub = Decimal("0")
        tmcc_liab_rub = Decimal("0")
        as_of: date | None = None
        for acc in accounts:
            snap = latest_snap.get(acc["id"])
            if snap is None:
                continue
            bal = Decimal(str(snap["actual_balance"]))
            rub = to_rub(bal, acc.get("currency") or "rub")
            snap_date_str = (snap.get("created_at") or "")[:10]
            try:
                snap_date = date.fromisoformat(snap_date_str) if snap_date_str else None
            except ValueError:
                snap_date = None
            if snap_date and (as_of is None or snap_date > as_of):
                as_of = snap_date
            if tmcc_id is not None and acc["id"] == tmcc_id:
                tmcc_liab_rub += -rub
            else:
                liquid_rub += rub

        running_liquid = liquid_rub
        running_tmcc_liab = tmcc_liab_rub

        months_out: list[dict[str, Any]] = []
        cur_year, cur_month = start_month.year, start_month.month
        while True:
            cur_key = f"{cur_year:04d}-{cur_month:02d}"
            month_first = date(cur_year, cur_month, 1)
            month_last = date(cur_year, cur_month, calendar.monthrange(cur_year, cur_month)[1])

            income_rub = Decimal("0")
            expense_liquid_rub = Decimal("0")
            expense_tmcc_rub = Decimal("0")
            tmcc_grace_rub = Decimal("0")
            line_items: list[dict[str, Any]] = []

            for tx in txs:
                tx_date_str = (tx.get("occurred_at") or "")[:10]
                try:
                    tx_d = date.fromisoformat(tx_date_str)
                except ValueError:
                    continue
                if tx_d < month_first or tx_d > month_last:
                    continue

                cur = (tx.get("currency") or "rub").lower()
                amt = Decimal(str(tx["amount"]))
                rub = to_rub(amt, cur)
                direction = (tx.get("direction") or "").lower()

                is_tmcc_funded = (tmcc_id is not None and tx.get("account_id") == tmcc_id)
                desc = tx.get("description") or ""
                tag = tx.get("primary_tag") or ""
                is_grace_pmt = (
                    direction == "expense"
                    and not is_tmcc_funded
                    and tag == "debt_repayment"
                    and "tmcc" in desc.lower()
                )

                if direction == "income":
                    income_rub += rub
                    bucket = "liquid"
                elif is_tmcc_funded:
                    expense_tmcc_rub += rub
                    bucket = "tmcc"
                else:
                    expense_liquid_rub += rub
                    if is_grace_pmt:
                        tmcc_grace_rub += rub
                    bucket = "liquid"

                line_items.append({
                    "date": tx_d.isoformat(),
                    "direction": direction,
                    "amount": float(amt),
                    "currency": cur,
                    "rub_equiv": float(rub),
                    "primary_tag": tx.get("primary_tag"),
                    "description": tx.get("description"),
                    "bucket": bucket,
                })

            delta_liquid = income_rub - expense_liquid_rub
            running_liquid = running_liquid + delta_liquid
            running_tmcc_liab = running_tmcc_liab - tmcc_grace_rub + expense_tmcc_rub
            end_net_wealth = running_liquid - running_tmcc_liab

            months_out.append({
                "month": cur_key,
                "income_rub": float(income_rub),
                "expense_liquid_rub": float(expense_liquid_rub),
                "expense_tmcc_rub": float(expense_tmcc_rub),
                "tmcc_grace_payments_rub": float(tmcc_grace_rub),
                "delta_liquid_rub": float(delta_liquid),
                "end_liquid_rub": float(running_liquid),
                "end_tmcc_liab_rub": float(running_tmcc_liab),
                "end_net_wealth_rub": float(end_net_wealth),
                "line_items": line_items,
            })

            if cur_year == end_month.year and cur_month == end_month.month:
                break
            cur_month += 1
            if cur_month > 12:
                cur_month = 1
                cur_year += 1

        return {
            "window": {
                "start": f"{start_month.year:04d}-{start_month.month:02d}",
                "end": f"{end_month.year:04d}-{end_month.month:02d}",
            },
            "starting_position": {
                "liquid_rub": float(liquid_rub),
                "tmcc_liability_rub": float(tmcc_liab_rub),
                "net_wealth_rub": float(liquid_rub - tmcc_liab_rub),
                "as_of": as_of.isoformat() if as_of else None,
            },
            "months": months_out,
        }

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

        def _ym_bounds(ym_from: str, ym_to: str) -> tuple[str, str, str, str]:
            """Return (date_start, date_end, dt_start_iso, dt_end_iso).

            Date strings are used for in-Python bucket comparison against
            occurred_at[:10]. Datetime strings (timezone-aware, end-of-day)
            are used for the PostgREST filter so we don't truncate the last
            day of timestamptz-stored transactions.
            """
            fy, fm = [int(x) for x in ym_from.split("-")]
            ty, tm = [int(x) for x in ym_to.split("-")]
            last_day = _cal.monthrange(ty, tm)[1]
            d_start = _dt.date(fy, fm, 1).isoformat()
            d_end = _dt.date(ty, tm, last_day).isoformat()
            dt_start = _dt.datetime(fy, fm, 1, tzinfo=timezone.utc).isoformat()
            dt_end = _dt.datetime(ty, tm, last_day, 23, 59, 59, tzinfo=timezone.utc).isoformat()
            return d_start, d_end, dt_start, dt_end

        curr_start, curr_end, curr_start_dt, curr_end_dt = _ym_bounds(period_from, period_to)
        prev_start, prev_end, prev_start_dt, prev_end_dt = _ym_bounds(prev_from, prev_to)
        # PostgREST range covers both windows; filter into buckets in Python.
        full_start_dt = min(curr_start_dt, prev_start_dt)
        full_end_dt = max(curr_end_dt, prev_end_dt)
        # FX window: 14d before the earliest period start, latest needed = full_end_dt's date.
        full_start_date = _dt.date.fromisoformat(full_start_dt[:10])
        fx_window_start = (full_start_date - _dt.timedelta(days=14)).isoformat()

        s = get_settings()
        with SupabaseClient(s.supabase_url, s.supabase_service_role_key) as sb:
            txs = sb.get("transactions", {
                "select": "occurred_at,amount,currency,primary_tag",
                "household_id": f"eq.{household_id}",
                "direction": "eq.expense",
                "is_planned": "eq.false",
                "is_internal_transfer": "eq.false",
                "is_skipped": "eq.false",
                "occurred_at": [f"gte.{full_start_dt}", f"lte.{full_end_dt}"],
                "limit": "50000",
            })
            fx_rows = sb.get("fx_rates", {
                "select": "from_currency,rate,date",
                "to_currency": "eq.RUB",
                "date": [f"gte.{fx_window_start}", f"lte.{full_end_dt[:10]}"],
                "order": "date.desc",
            })

        fx_by_cur = _build_fx_lookup(fx_rows)

        curr_by_tag: dict[str, float] = {}
        prior_by_tag: dict[str, float] = {}
        curr_total = 0.0
        prior_total = 0.0

        for tx in txs:
            occ = (tx.get("occurred_at") or "")[:10]
            amount_rub = _rub_on_date(float(tx["amount"]), tx.get("currency"), occ, fx_by_cur)
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

    # ─── Per-month totals (actual + planned) — replaces monthly_totals RPC ──

    def monthly_totals_via_rest(
        self,
        household_id: str,
        p_from: str,   # YYYY-MM inclusive
        p_to: str,     # YYYY-MM inclusive
    ) -> list[dict[str, Any]]:
        """Per-month income/expense totals across [p_from..p_to], RUB-converted.

        Returns one row per (year, month) within the window that has any matching
        transaction. Each row includes both actual and planned aggregates so the
        dashboard can render planned future months without polluting actual
        totals. Direction restricted to income/expense; internal transfers and
        skipped rows are excluded everywhere.

        Replaces the Supabase RPC `monthly_totals` (which only returned
        actual_* and lives outside of Python migrations).
        """
        from app.infrastructure.config.settings import get_settings
        from app.infrastructure.supabase import SupabaseClient
        import calendar as _cal
        import datetime as _dt

        fy, fm = [int(x) for x in p_from.split("-")]
        ty, tm = [int(x) for x in p_to.split("-")]
        last_day = _cal.monthrange(ty, tm)[1]
        window_start = _dt.datetime(fy, fm, 1, tzinfo=timezone.utc)
        dt_start = window_start.isoformat()
        dt_end = _dt.datetime(ty, tm, last_day, 23, 59, 59, tzinfo=timezone.utc).isoformat()
        fx_window_start = (window_start - _dt.timedelta(days=14)).date().isoformat()

        s = get_settings()
        with SupabaseClient(s.supabase_url, s.supabase_service_role_key) as sb:
            txs = sb.get("transactions", {
                "select": "occurred_at,direction,amount,currency,is_planned",
                "household_id": f"eq.{household_id}",
                "direction": "in.(income,expense)",
                "is_internal_transfer": "eq.false",
                "is_skipped": "eq.false",
                "occurred_at": [f"gte.{dt_start}", f"lte.{dt_end}"],
                "limit": "50000",
            })
            fx_rows = sb.get("fx_rates", {
                "select": "from_currency,rate,date",
                "to_currency": "eq.RUB",
                "date": [f"gte.{fx_window_start}", f"lte.{dt_end[:10]}"],
                "order": "date.desc",
            })

        fx_by_cur = _build_fx_lookup(fx_rows)

        buckets: dict[tuple[int, int], dict[str, float]] = {}
        for tx in txs:
            occ = tx.get("occurred_at") or ""
            try:
                y = int(occ[0:4])
                mo = int(occ[5:7])
            except (ValueError, IndexError):
                continue
            key = (y, mo)
            b = buckets.setdefault(key, {
                "actual_income_rub": 0.0,
                "actual_expense_rub": 0.0,
                "planned_income_rub": 0.0,
                "planned_expense_rub": 0.0,
            })
            amt = _rub_on_date(float(tx["amount"]), tx.get("currency"), occ, fx_by_cur)
            direction = tx.get("direction")
            is_planned = bool(tx.get("is_planned"))
            field = (
                "planned_income_rub"  if is_planned and direction == "income"  else
                "planned_expense_rub" if is_planned and direction == "expense" else
                "actual_income_rub"   if direction == "income"                 else
                "actual_expense_rub"
            )
            b[field] += amt

        out: list[dict[str, Any]] = []
        for (y, mo), b in sorted(buckets.items()):
            out.append({"y": y, "mo": mo, **b})
        return out

    # ─── Legacy: keep for existing API routes ─────────────────────────────────

    def upcoming_payments(self, household_id: str, days: int = 7, until_date: date | None = None) -> list[dict[str, Any]]:
        """Alias → upcoming_planned() for backward compatibility with API routes."""
        return self.upcoming_planned(household_id, days=days, until_date=until_date)

    # ─── Reconciliation drift ──────────────────────────────────────────────

    def _account_drift(self, account_id, latest_snap) -> tuple[float | None, float | None]:
        """Derived reconciliation drift for one account.

        ``computed`` = the snapshot *before* ``latest_snap`` plus the signed sum
        of real transactions attributed to the account in the window between the
        two snapshots (by ``occurred_at``). ``drift`` = reported − computed.

        Returns ``(None, None)`` when there is no prior snapshot (nothing to
        reconcile). Because attribution is by ``occurred_at``, a past-dated
        expense added later lands in the window and shrinks the drift — the
        on-the-fly behavior that replaces the old fixed «корректировка» tx.
        """
        if latest_snap is None:
            return None, None
        prev = (
            self.db.query(BalanceSnapshot)
            .filter(
                BalanceSnapshot.account_id == account_id,
                BalanceSnapshot.created_at < latest_snap.created_at,
            )
            .order_by(BalanceSnapshot.created_at.desc())
            .first()
        )
        if prev is None:
            return None, None
        txs = (
            self.db.query(Transaction)
            .filter(
                Transaction.account_id == account_id,
                Transaction.occurred_at > prev.created_at,
                Transaction.occurred_at <= latest_snap.created_at,
                Transaction.is_planned == False,  # noqa: E712 — ЗАКОН
                Transaction.is_internal_transfer == False,  # noqa: E712 — ЗАКОН
                Transaction.is_skipped == False,  # noqa: E712
                Transaction.direction.in_(
                    [TransactionDirection.INCOME, TransactionDirection.EXPENSE]
                ),
            )
            .all()
        )
        delta = Decimal("0")
        for tx in txs:
            amt = Decimal(str(tx.amount))
            if tx.direction == TransactionDirection.INCOME:
                delta += amt
            else:
                delta -= amt
        computed = Decimal(str(prev.actual_balance)) + delta
        drift = Decimal(str(latest_snap.actual_balance)) - computed
        return float(computed), float(drift)

    # ─── Data-health home page ─────────────────────────────────────────────

    def data_health(self, household_id: str, current_user_id: str | None = None) -> dict[str, Any]:
        """How complete and fresh the household's finance data is, plus a
        per-person to-do split keyed on `users` (transactions carry `user_id`;
        accounts carry `owner_user_id`). `current_user_id` (the logged-in
        session uid) is flagged `is_you` so the page can personalise.
        Read-only visibility surface. Mirror any change in data_health_via_rest()."""
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id
        cur_uid = _uuid.UUID(current_user_id) if current_user_id else None
        now = datetime.now(timezone.utc)

        def _age_days(dt: datetime | None) -> int | None:
            if dt is None:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (now - dt).days

        user_names = {
            u.id: u.name
            for u in self.db.query(User).filter(
                User.household_id == hid, User.is_active == True  # noqa: E712
            ).all()
        }
        people = {uid: {"user_id": str(uid), "name": name, "is_you": uid == cur_uid, "todos": []}
                  for uid, name in user_names.items()}
        unassigned: list[dict[str, Any]] = []

        def _route(uid, todo):
            if uid and uid in people:
                people[uid]["todos"].append(todo)
            else:
                unassigned.append(todo)

        # ── Uncategorized (primary_tag is what categorization actually writes)
        uncat_rows = (
            self.db.query(Transaction)
            .filter(
                Transaction.household_id == hid,
                Transaction.primary_tag.is_(None),
                Transaction.is_planned == False,  # noqa: E712 — ЗАКОН
                Transaction.is_internal_transfer == False,  # noqa: E712 — ЗАКОН
                Transaction.direction != TransactionDirection.EXCHANGE,
            )
            .order_by(Transaction.occurred_at.asc())
            .all()
        )
        uncat_items = [
            {
                "id": str(tx.id),
                "occurred_at": tx.occurred_at.isoformat() if tx.occurred_at else None,
                "amount": float(tx.amount),
                "currency": (tx.currency.value if hasattr(tx.currency, "value") else tx.currency),
                "merchant": tx.merchant_raw or "",
                "user_id": str(tx.user_id) if tx.user_id else None,
                "user_name": user_names.get(tx.user_id),
            }
            for tx in uncat_rows[:UNCAT_ITEM_CAP]
        ]
        uncat_count = len(uncat_rows)
        oldest_days = _age_days(uncat_rows[0].occurred_at) if uncat_rows else None
        uncat_status = _signal_uncat_status(uncat_count, oldest_days)
        for tx in uncat_rows:
            _route(tx.user_id, {
                "kind": "uncategorized",
                "label": f"{tx.merchant_raw or 'операция'} — {float(tx.amount):g} {(tx.currency.value if hasattr(tx.currency, 'value') else tx.currency)}",
                "ref": str(tx.id),
            })

        # ── Stale balances (latest snapshot per active account)
        accounts = (
            self.db.query(Account)
            .filter(Account.household_id == hid, Account.is_active == True)  # noqa: E712
            .order_by(Account.name.asc())
            .all()
        )
        bal_accounts: list[dict[str, Any]] = []
        for acct in accounts:
            latest = (
                self.db.query(BalanceSnapshot)
                .filter(BalanceSnapshot.account_id == acct.id)
                .order_by(BalanceSnapshot.created_at.desc())
                .first()
            )
            age = _age_days(latest.created_at) if latest else None
            status = _status_from_age(age, BAL_WARN_D, BAL_ERR_D)
            computed, drift = self._account_drift(acct.id, latest)
            drift_status = _drift_status(drift)
            bal_accounts.append({
                "account_id": str(acct.id),
                "name": acct.name,
                "currency": (acct.currency.value if hasattr(acct.currency, "value") else acct.currency),
                "last_balance": float(latest.actual_balance) if latest else None,
                "last_verified_at": latest.created_at.isoformat() if latest else None,
                "age_days": age,
                "status": status,
                "computed_balance": computed,
                "drift": drift,
                "drift_status": drift_status,
                "user_id": str(acct.owner_user_id) if acct.owner_user_id else None,
                "user_name": user_names.get(acct.owner_user_id),
            })
            if status in ("amber", "red"):
                _route(acct.owner_user_id, {
                    "kind": "balance",
                    "label": f"Сверить баланс: {acct.name}",
                    "ref": str(acct.id),
                })
            if drift_status != "green":
                _route(acct.owner_user_id, {
                    "kind": "drift",
                    "label": f"Разобрать расхождение: {acct.name}",
                    "ref": str(acct.id),
                })
        bal_status = _worst([a["status"] for a in bal_accounts] + [a["drift_status"] for a in bal_accounts])

        # ── Import freshness (latest imported_at per source_name)
        raw_rows = (
            self.db.query(RawImportTransaction)
            .filter(RawImportTransaction.household_id == hid)
            .all()
        )
        latest_by_source: dict[str, datetime] = {}
        for r in raw_rows:
            cur = latest_by_source.get(r.source_name)
            if cur is None or (r.imported_at and r.imported_at > cur):
                latest_by_source[r.source_name] = r.imported_at
        sources: list[dict[str, Any]] = []
        for name in sorted(latest_by_source):
            age = _age_days(latest_by_source[name])
            sources.append({
                "source_name": name,
                "last_imported_at": latest_by_source[name].isoformat() if latest_by_source[name] else None,
                "age_days": age,
                "status": _status_from_age(age, IMPORT_WARN_D, IMPORT_ERR_D),
            })
        import_status = _worst([s["status"] for s in sources])
        last_activity = (
            self.db.query(Transaction.created_at)
            .filter(Transaction.household_id == hid)
            .order_by(Transaction.created_at.desc())
            .first()
        )
        last_activity_at = last_activity[0].isoformat() if last_activity and last_activity[0] else None

        attention_count = (
            uncat_count
            + sum(1 for a in bal_accounts if a["status"] in ("amber", "red"))
            + sum(1 for a in bal_accounts if a["drift_status"] != "green")
            + sum(1 for s in sources if s["status"] in ("amber", "red"))
        )

        return {
            "generated_at": now.isoformat(),
            "attention_count": attention_count,
            "uncategorized": {
                "count": uncat_count,
                "oldest_days": oldest_days,
                "status": uncat_status,
                "items": uncat_items,
            },
            "balances": {"status": bal_status, "accounts": bal_accounts},
            "imports": {
                "status": import_status,
                "sources": sources,
                "last_activity_at": last_activity_at,
            },
            "people": sorted(people.values(), key=lambda p: not p["is_you"]),
            "unassigned": unassigned,
        }

    def data_health_via_rest(self, household_id: str, current_user_id: str | None = None) -> dict[str, Any]:
        """REST-API variant of data_health(). Talks to PostgREST via
        SupabaseClient instead of opening a Postgres socket. Same return shape.
        Keep structurally in sync with data_health()."""
        from app.infrastructure.config.settings import get_settings
        from app.infrastructure.supabase import SupabaseClient

        settings = get_settings()
        now = datetime.now(timezone.utc)

        def _age_from_iso(iso: str | None) -> int | None:
            if not iso:
                return None
            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except ValueError:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (now - dt).days

        with SupabaseClient(settings.supabase_url, settings.supabase_service_role_key) as sb:
            users = sb.get("users", {
                "select": "id,name",
                "household_id": f"eq.{household_id}",
                "is_active": "eq.true",
            })
            uncat = sb.get("transactions", {
                "select": "id,occurred_at,amount,currency,merchant_raw,user_id",
                "household_id": f"eq.{household_id}",
                "primary_tag": "is.null",
                "is_planned": "eq.false",
                "is_internal_transfer": "eq.false",
                "direction": "neq.exchange",
                "order": "occurred_at.asc",
            })
            accounts = sb.get("accounts", {
                "select": "id,name,currency,owner_user_id",
                "household_id": f"eq.{household_id}",
                "is_active": "eq.true",
                "order": "name.asc",
            })
            account_ids = [a["id"] for a in accounts]
            snap_rows = []
            if account_ids:
                snap_rows = sb.get("balance_snapshots", {
                    "select": "account_id,actual_balance,created_at",
                    "account_id": f"in.({','.join(account_ids)})",
                    "order": "account_id.asc,created_at.desc",
                })
            # Real, account-attributed txns for drift derivation (ЗАКОН filters).
            attributed_rows = sb.get("transactions", {
                "select": "account_id,occurred_at,amount,direction,is_planned,is_internal_transfer,is_skipped",
                "household_id": f"eq.{household_id}",
                "is_planned": "eq.false",
                "is_internal_transfer": "eq.false",
                "is_skipped": "eq.false",
                "direction": "in.(income,expense)",
            })
            raw_rows = sb.get("raw_import_transactions", {
                "select": "source_name,imported_at",
                "household_id": f"eq.{household_id}",
                "order": "imported_at.desc",
            })
            last_act_rows = sb.get("transactions", {
                "select": "created_at",
                "household_id": f"eq.{household_id}",
                "order": "created_at.desc",
                "limit": "1",
            })

        user_names = {u["id"]: u["name"] for u in users}

        uncat_items = [
            {
                "id": tx["id"],
                "occurred_at": tx.get("occurred_at"),
                "amount": float(tx["amount"]),
                "currency": tx.get("currency") or "rub",
                "merchant": tx.get("merchant_raw") or "",
                "user_id": tx.get("user_id"),
                "user_name": user_names.get(tx.get("user_id")),
            }
            for tx in uncat[:UNCAT_ITEM_CAP]
        ]
        uncat_count = len(uncat)
        oldest_days = _age_from_iso(uncat[0]["occurred_at"]) if uncat else None
        uncat_status = _signal_uncat_status(uncat_count, oldest_days)

        # All snapshots per account, latest-first (snap_rows already created_at desc).
        snaps_by_acct: dict[str, list[dict]] = {}
        for r in snap_rows:
            snaps_by_acct.setdefault(r["account_id"], []).append(r)

        def _parse_iso(iso: str | None):
            if not iso:
                return None
            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except ValueError:
                return None
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

        def _drift_rest(account_id: str) -> tuple[float | None, float | None]:
            snaps = snaps_by_acct.get(account_id, [])
            if len(snaps) < 2:
                return None, None
            latest_s, prev_s = snaps[0], snaps[1]
            lo, hi = _parse_iso(prev_s["created_at"]), _parse_iso(latest_s["created_at"])
            delta = Decimal("0")
            for t in attributed_rows:
                if t.get("account_id") != account_id:
                    continue
                occ = _parse_iso(t.get("occurred_at"))
                if occ is None or lo is None or hi is None or not (lo < occ <= hi):
                    continue
                amt = Decimal(str(t.get("amount") or 0))
                if (t.get("direction") or "").lower() == "income":
                    delta += amt
                else:
                    delta -= amt
            computed = Decimal(str(prev_s["actual_balance"])) + delta
            drift = Decimal(str(latest_s["actual_balance"])) - computed
            return float(computed), float(drift)

        latest_snap: dict[str, dict] = {k: v[0] for k, v in snaps_by_acct.items()}
        bal_accounts = []
        for a in accounts:
            snap = latest_snap.get(a["id"])
            age = _age_from_iso(snap["created_at"]) if snap else None
            computed, drift = _drift_rest(a["id"])
            bal_accounts.append({
                "account_id": a["id"],
                "name": a["name"],
                "currency": a.get("currency") or "rub",
                "last_balance": float(snap["actual_balance"]) if snap else None,
                "last_verified_at": snap["created_at"] if snap else None,
                "age_days": age,
                "status": _status_from_age(age, BAL_WARN_D, BAL_ERR_D),
                "computed_balance": computed,
                "drift": drift,
                "drift_status": _drift_status(drift),
                "user_id": a.get("owner_user_id"),
                "user_name": user_names.get(a.get("owner_user_id")),
            })
        bal_status = _worst([a["status"] for a in bal_accounts] + [a["drift_status"] for a in bal_accounts])

        latest_by_source: dict[str, str] = {}
        for r in raw_rows:
            if r["source_name"] not in latest_by_source:
                latest_by_source[r["source_name"]] = r["imported_at"]
        sources = []
        for name in sorted(latest_by_source):
            age = _age_from_iso(latest_by_source[name])
            sources.append({
                "source_name": name,
                "last_imported_at": latest_by_source[name],
                "age_days": age,
                "status": _status_from_age(age, IMPORT_WARN_D, IMPORT_ERR_D),
            })
        import_status = _worst([s["status"] for s in sources])
        last_activity_at = last_act_rows[0]["created_at"] if last_act_rows else None

        cur_uid = str(current_user_id) if current_user_id else None
        people = {uid: {"user_id": uid, "name": name, "is_you": uid == cur_uid, "todos": []}
                  for uid, name in user_names.items()}
        unassigned = []

        def _route(uid, todo):
            if uid and uid in people:
                people[uid]["todos"].append(todo)
            else:
                unassigned.append(todo)

        for tx in uncat:
            _route(tx.get("user_id"), {
                "kind": "uncategorized",
                "label": f"{tx.get('merchant_raw') or 'операция'} — {float(tx['amount']):g} {tx.get('currency') or 'rub'}",
                "ref": tx["id"],
            })
        for acct in bal_accounts:
            if acct["status"] in ("amber", "red"):
                _route(acct["user_id"], {
                    "kind": "balance",
                    "label": f"Сверить баланс: {acct['name']}",
                    "ref": acct["account_id"],
                })
            if acct["drift_status"] != "green":
                _route(acct["user_id"], {
                    "kind": "drift",
                    "label": f"Разобрать расхождение: {acct['name']}",
                    "ref": acct["account_id"],
                })

        attention_count = (
            uncat_count
            + sum(1 for a in bal_accounts if a["status"] in ("amber", "red"))
            + sum(1 for a in bal_accounts if a["drift_status"] != "green")
            + sum(1 for s in sources if s["status"] in ("amber", "red"))
        )

        return {
            "generated_at": now.isoformat(),
            "attention_count": attention_count,
            "uncategorized": {
                "count": uncat_count,
                "oldest_days": oldest_days,
                "status": uncat_status,
                "items": uncat_items,
            },
            "balances": {"status": bal_status, "accounts": bal_accounts},
            "imports": {
                "status": import_status,
                "sources": sources,
                "last_activity_at": last_activity_at,
            },
            "people": sorted(people.values(), key=lambda p: not p["is_you"]),
            "unassigned": unassigned,
        }


def _derive_status(tx: Transaction) -> str:
    """Derive UI display status from transaction state.

    actual    — normal recorded transaction
    planned   — future planned entry not yet overdue
    overdue   — planned entry whose date has passed
    unplanned — user explicitly marked with [сюрприз] or [surprise]
    """
    today = date.today()
    occurred = tx.occurred_at.date() if hasattr(tx.occurred_at, "date") else tx.occurred_at

    if tx.is_planned:
        if occurred <= today:
            return "overdue"
        return "planned"

    raw = (tx.merchant_raw or "").lower()
    if "[сюрприз]" in raw or "[surprise]" in raw:
        return "unplanned"

    return "actual"
