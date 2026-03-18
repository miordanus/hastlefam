"""fx_service.py — daily FX rate fetching and RUB conversion.

Fetches rates from exchangerate-api.com (free tier, no key required for /latest).
Stores in fx_rates table for offline use.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# Currencies to fetch (target: RUB conversions)
_TRACKED = ["USD", "EUR", "PLN", "USDT", "AMD"]
_BASE_URL = "https://v6.exchangerate-api.com/v6/latest/RUB"


async def fetch_and_store_rates() -> None:
    """Fetch today's FX rates and upsert into fx_rates table.

    Rates are stored as X RUB = 1 foreign_currency (i.e. how many RUB per 1 unit).
    Degrades gracefully: logs WARNING on any error, never raises.
    """
    from app.infrastructure.db.session import SessionLocal
    from app.infrastructure.db.models import FxRate

    today = date.today()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_BASE_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log.warning("fx_service: failed to fetch rates: %s", exc)
        return

    conversion_rates = data.get("conversion_rates", {})
    if not conversion_rates:
        log.warning("fx_service: empty conversion_rates in response")
        return

    try:
        with SessionLocal() as db:
            for foreign_cur in _TRACKED:
                rate_foreign_per_rub = conversion_rates.get(foreign_cur)
                if rate_foreign_per_rub is None or float(rate_foreign_per_rub) == 0:
                    continue
                # We want: how many RUB = 1 foreign unit
                # API gives: 1 RUB = rate_foreign_per_rub FOREIGN
                # So: 1 FOREIGN = 1 / rate_foreign_per_rub RUB
                rub_per_foreign = Decimal("1") / Decimal(str(rate_foreign_per_rub))

                db.execute(
                    __import__("sqlalchemy").text("""
                        INSERT INTO fx_rates (id, date, from_currency, to_currency, rate, created_at)
                        VALUES (gen_random_uuid(), :date, :from_cur, 'RUB', :rate, now())
                        ON CONFLICT (date, from_currency, to_currency)
                        DO UPDATE SET rate = EXCLUDED.rate
                    """),
                    {"date": today, "from_cur": foreign_cur, "rate": float(rub_per_foreign)},
                )
            db.commit()
        log.info("fx_service: rates updated for %s", today)
    except Exception as exc:
        log.warning("fx_service: failed to store rates: %s", exc)


def convert_to_rub(
    amount: Decimal,
    currency: str,
    for_date: date,
    db: Session,
) -> Decimal | None:
    """Convert amount in given currency to RUB.

    Returns RUB equivalent or None if no rate available within 7 days.
    """
    if currency == "RUB":
        return amount

    import sqlalchemy as sa
    from app.infrastructure.db.models import FxRate

    # Look up rate for exact date, falling back to last 7 days
    row = (
        db.query(FxRate)
        .filter(
            FxRate.from_currency == currency,
            FxRate.to_currency == "RUB",
            FxRate.date >= for_date - timedelta(days=7),
            FxRate.date <= for_date,
        )
        .order_by(FxRate.date.desc())
        .first()
    )
    if row is None:
        return None
    return (amount * Decimal(str(row.rate))).quantize(Decimal("0.01"))
