"""Tests for the Quality tab: untagged listing + bulk tagging (#4)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import MerchantTagRule, Transaction
from tests.conftest import HOUSEHOLD_ID


def _tx(db, *, primary_tag=None, is_planned=False, is_internal_transfer=False,
        direction=TransactionDirection.EXPENSE, merchant="пятёрочка", amount=100):
    tx = Transaction(
        id=uuid.uuid4(), household_id=HOUSEHOLD_ID, direction=direction,
        amount=amount, currency=Currency.RUB,
        occurred_at=datetime.now(timezone.utc), merchant_raw=merchant,
        source="test", parse_status="ok", is_planned=is_planned,
        is_internal_transfer=is_internal_transfer, is_skipped=False,
        primary_tag=primary_tag, extra_tags=[],
    )
    db.add(tx)
    return tx


def test_untagged_excludes_planned_internal_exchange_and_tagged(seeded_db):
    _tx(seeded_db, primary_tag=None)                                  # untagged → included
    _tx(seeded_db, primary_tag="еда")                                 # tagged → excluded
    _tx(seeded_db, primary_tag=None, is_planned=True)                 # planned → excluded
    _tx(seeded_db, primary_tag=None, is_internal_transfer=True)       # internal → excluded
    _tx(seeded_db, primary_tag=None, direction=TransactionDirection.EXCHANGE)  # exchange → excluded
    seeded_db.commit()

    out = FinanceService(seeded_db).untagged_transactions(str(HOUSEHOLD_ID))
    assert out["count"] == 1


def test_untagged_attaches_autocat_suggestion(seeded_db):
    seeded_db.add(MerchantTagRule(
        id=uuid.uuid4(), household_id=HOUSEHOLD_ID,
        merchant_pattern="пятёрочка", tag="еда", is_active=True,
    ))
    _tx(seeded_db, primary_tag=None, merchant="Пятёрочка")
    seeded_db.commit()

    out = FinanceService(seeded_db).untagged_transactions(str(HOUSEHOLD_ID))
    assert out["items"][0]["suggested_tag"] == "еда"
    assert "еда" in out["known_tags"]


def test_bulk_tag_writes_lowercased_tags(seeded_db):
    a = _tx(seeded_db, primary_tag=None)
    b = _tx(seeded_db, primary_tag=None)
    seeded_db.commit()

    res = FinanceService(seeded_db).bulk_tag([
        {"tx_id": str(a.id), "tag": "#Еда"},
        {"tx_id": str(b.id), "tag": ""},      # empty → skipped
    ])
    assert res["updated"] == 1
    seeded_db.refresh(a)
    assert a.primary_tag == "еда"


def test_bulk_tag_via_rest_groups_by_tag(mock_supabase):
    res = FinanceService.bulk_tag_via_rest([
        {"tx_id": "1", "tag": "еда"},
        {"tx_id": "2", "tag": "еда"},
        {"tx_id": "3", "tag": "транспорт"},
    ])
    assert res["updated"] == 3
    # One PATCH per distinct tag (2 tags → 2 patch calls), each with id=in.(...).
    assert len(mock_supabase.patch_calls) == 2
    tags_written = sorted(body["primary_tag"] for _, _, body in mock_supabase.patch_calls)
    assert tags_written == ["еда", "транспорт"]
