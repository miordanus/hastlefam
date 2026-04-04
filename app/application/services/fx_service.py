"""fx_service.py — daily FX rate fetching and RUB conversion.

Fetches rates from the Central Bank of Russia (CBR) daily XML feed.
No API key required. Stores in fx_rates table for offline use.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# Currencies to fetch (target: RUB conversions)
_TRACKED = ["USD", "EUR", "PLN"]

# CBR daily XML feed — returns rates for all currencies vs RUB
_CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"

# CBR uses its own currency codes; map ours to CBR char codes
_CBR_CHAR_CODES = {"USD": "USD", "EUR": "EUR", "PLN": "PLN"}

# Crypto / non-CBR currencies — hardcoded or fetched separately
# USDT is ~1 USD, AMD needs a different source; we handle them as fallbacks
_USDT_PROXY = "USD"  # USDT ≈ USD rate


async def fetch_and_store_rates() -> None:
    """Fetch today's FX rates from CBR and upsert into fx_rates table.

    Rates are stored as: 1 foreign_currency = X RUB (how many RUB per 1 unit).
    Degrades gracefully: logs WARNING on any error, never raises.
    """
    from app.infrastructure.db.session import SessionLocal

    today = date.today()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _CBR_URL,
                params={"date_req": today.strftime("%d/%m/%Y")},
            )
            resp.raise_for_status()
            # CBR returns windows-1251 encoded XML
            xml_text = resp.content.decode("windows-1251")
    except Exception as exc:
        log.warning("fx_service: failed to fetch CBR rates: %s", exc)
        return

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("fx_service: failed to parse CBR XML: %s", exc)
        return

    # Parse CBR XML: <Valute><CharCode>USD</CharCode><Nominal>1</Nominal><Value>92,1234</Value></Valute>
    cbr_rates: dict[str, Decimal] = {}
    for valute in root.findall("Valute"):
        char_code = valute.findtext("CharCode", "")
        nominal_str = valute.findtext("Nominal", "1")
        value_str = valute.findtext("Value", "")
        if not char_code or not value_str:
            continue
        try:
            nominal = Decimal(nominal_str.replace(",", "."))
            value = Decimal(value_str.replace(",", "."))
            # Rate per 1 unit of foreign currency in RUB
            rate_per_one = value / nominal
            cbr_rates[char_code] = rate_per_one
        except Exception:
            continue

    if not cbr_rates:
        log.warning("fx_service: no rates parsed from CBR XML")
        return

    try:
        with SessionLocal() as db:
            try:
                for our_code in _TRACKED:
                    cbr_code = _CBR_CHAR_CODES.get(our_code, our_code)
                    rate = cbr_rates.get(cbr_code)
                    if rate is None:
                        continue
                    _upsert_rate(db, today, our_code, rate)

                # USDT ≈ USD (proxy)
                usd_rate = cbr_rates.get("USD")
                if usd_rate is not None:
                    _upsert_rate(db, today, "USDT", usd_rate)

                # AMD — CBR has it as well
                amd_rate = cbr_rates.get("AMD")
                if amd_rate is not None:
                    _upsert_rate(db, today, "AMD", amd_rate)

                db.commit()
                log.info("fx_service: CBR rates updated for %s", today)
            except Exception as exc:
                import psycopg.errors as _pg_errors  # psycopg v3

                db.rollback()
                if isinstance(exc.__cause__, _pg_errors.UndefinedTable) or isinstance(
                    exc, _pg_errors.UndefinedTable
                ):
                    log.warning(
                        "fx_rates table not found, skipping rate storage"
                        " (run migrations to enable FX rate persistence)"
                    )
                else:
                    log.warning("fx_service: failed to store rates: %s", exc)
    except Exception as exc:
        log.warning("fx_service: failed to open DB session for rate storage: %s", exc)


def _upsert_rate(db, for_date: date, from_currency: str, rate: Decimal) -> None:
    """Insert or update a single FX rate row."""
    import sqlalchemy as sa

    db.execute(
        sa.text("""
            INSERT INTO hastlefam.fx_rates (id, date, from_currency, to_currency, rate, created_at)
            VALUES (gen_random_uuid(), :date, :from_cur, 'RUB', :rate, now())
            ON CONFLICT (date, from_currency, to_currency)
            DO UPDATE SET rate = EXCLUDED.rate
        """),
        {"date": for_date, "from_cur": from_currency, "rate": float(rate)},
    )


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
