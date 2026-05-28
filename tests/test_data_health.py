import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import (
    Account,
    BalanceSnapshot,
    RawImportTransaction,
    Transaction,
    User,
)
from tests.conftest import ACCOUNT_ID, HOUSEHOLD_ID, USER_ID


def _now():
    return datetime.now(timezone.utc)


def _add_tx(db, *, primary_tag=None, days_ago=0, user_id=None,
            direction=TransactionDirection.EXPENSE, is_planned=False,
            is_internal_transfer=False):
    tx = Transaction(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        user_id=user_id,
        direction=direction,
        amount=Decimal("10"),
        currency=Currency.USD,
        occurred_at=_now() - timedelta(days=days_ago),
        merchant_raw="shop",
        source="test",
        parse_status="ok",
        parse_confidence=Decimal("0.9"),
        primary_tag=primary_tag,
        is_planned=is_planned,
        is_internal_transfer=is_internal_transfer,
    )
    db.add(tx)
    db.commit()
    return tx


def _add_account(db, *, name="Acct", owner_user_id=None, is_active=True):
    acct = Account(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        owner_user_id=owner_user_id,
        name=name,
        currency=Currency.USD,
        is_active=is_active,
    )
    db.add(acct)
    db.commit()
    return acct


def _add_snapshot(db, account_id, *, days_ago, balance="100"):
    snap = BalanceSnapshot(
        id=uuid.uuid4(),
        account_id=account_id,
        household_id=HOUSEHOLD_ID,
        actual_balance=Decimal(balance),
        created_at=_now() - timedelta(days=days_ago),
    )
    db.add(snap)
    db.commit()
    return snap


def _add_import(db, *, source_name, days_ago):
    row = RawImportTransaction(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        import_batch_id="b1",
        source_name=source_name,
        imported_at=_now() - timedelta(days=days_ago),
    )
    db.add(row)
    db.commit()
    return row


# ─── Uncategorized signal ──────────────────────────────────────────────────

def test_uncategorized_counts_untagged(seeded_db):
    _add_tx(seeded_db, primary_tag=None, days_ago=2)
    _add_tx(seeded_db, primary_tag=None, days_ago=5)
    _add_tx(seeded_db, primary_tag="groceries", days_ago=1)

    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    assert out["uncategorized"]["count"] == 2
    assert out["uncategorized"]["oldest_days"] == 5
    assert out["uncategorized"]["status"] == "amber"


def test_uncategorized_excludes_invariant_rows(seeded_db):
    _add_tx(seeded_db, primary_tag=None, is_planned=True)
    _add_tx(seeded_db, primary_tag=None, is_internal_transfer=True)
    _add_tx(seeded_db, primary_tag=None, direction=TransactionDirection.EXCHANGE)

    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    assert out["uncategorized"]["count"] == 0
    assert out["uncategorized"]["status"] == "green"


def test_uncategorized_red_when_old(seeded_db):
    _add_tx(seeded_db, primary_tag=None, days_ago=20)
    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    assert out["uncategorized"]["status"] == "red"


def test_uncategorized_red_when_many(seeded_db):
    for _ in range(11):
        _add_tx(seeded_db, primary_tag=None, days_ago=1)
    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    assert out["uncategorized"]["status"] == "red"


# ─── Balance freshness signal ──────────────────────────────────────────────

def test_balance_amber_and_red_by_age(seeded_db):
    a_amber = _add_account(seeded_db, name="Amber")
    a_red = _add_account(seeded_db, name="Red")
    _add_snapshot(seeded_db, a_amber.id, days_ago=10)
    _add_snapshot(seeded_db, a_red.id, days_ago=20)

    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    by_name = {a["name"]: a for a in out["balances"]["accounts"]}
    assert by_name["Amber"]["status"] == "amber"
    assert by_name["Amber"]["age_days"] == 10
    assert by_name["Red"]["status"] == "red"


def test_balance_never_verified_is_red(seeded_db):
    # seeded_db's ACCOUNT_ID account has no snapshot
    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    main = next(a for a in out["balances"]["accounts"] if a["account_id"] == str(ACCOUNT_ID))
    assert main["status"] == "red"
    assert main["age_days"] is None


def test_balance_uses_latest_snapshot(seeded_db):
    _add_snapshot(seeded_db, ACCOUNT_ID, days_ago=30, balance="50")
    _add_snapshot(seeded_db, ACCOUNT_ID, days_ago=2, balance="999")
    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    main = next(a for a in out["balances"]["accounts"] if a["account_id"] == str(ACCOUNT_ID))
    assert main["status"] == "green"
    assert main["age_days"] == 2
    assert main["last_balance"] == 999.0


def test_inactive_accounts_excluded(seeded_db):
    _add_account(seeded_db, name="Dead", is_active=False)
    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    assert all(a["name"] != "Dead" for a in out["balances"]["accounts"])


# ─── Import freshness signal ───────────────────────────────────────────────

def test_import_freshness_per_source(seeded_db):
    _add_import(seeded_db, source_name="tinkoff", days_ago=4)   # amber
    _add_import(seeded_db, source_name="tinkoff", days_ago=1)   # latest -> green
    _add_import(seeded_db, source_name="voice", days_ago=9)     # red

    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    by_src = {s["source_name"]: s for s in out["imports"]["sources"]}
    assert by_src["tinkoff"]["status"] == "green"
    assert by_src["tinkoff"]["age_days"] == 1
    assert by_src["voice"]["status"] == "red"
    assert out["imports"]["status"] == "red"  # worst of the sources


# ─── Per-person split ──────────────────────────────────────────────────────

def test_per_person_assignment(seeded_db):
    wife = User(id=uuid.uuid4(), household_id=HOUSEHOLD_ID, telegram_id="999", name="Wife")
    seeded_db.add(wife)
    seeded_db.commit()

    _add_tx(seeded_db, primary_tag=None, user_id=USER_ID, days_ago=1)
    _add_tx(seeded_db, primary_tag=None, user_id=wife.id, days_ago=1)
    _add_tx(seeded_db, primary_tag=None, user_id=None, days_ago=1)  # shared

    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID), current_user_id=str(USER_ID))
    people = {p["name"]: p for p in out["people"]}
    assert len(people["Test User"]["todos"]) == 1
    assert len(people["Wife"]["todos"]) == 1
    shared_uncat = [t for t in out["unassigned"] if t["kind"] == "uncategorized"]
    assert len(shared_uncat) == 1


def test_per_person_personalization_and_balance_routing(seeded_db):
    # logged-in user is flagged is_you and sorted first
    _add_account(seeded_db, name="Max card", owner_user_id=USER_ID)  # never verified -> red -> routed
    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID), current_user_id=str(USER_ID))
    assert out["people"][0]["is_you"] is True
    me = next(p for p in out["people"] if p["is_you"])
    assert any(t["kind"] == "balance" and "Max card" in t["label"] for t in me["todos"])


# ─── Headline aggregate ────────────────────────────────────────────────────

def test_attention_count_aggregates(seeded_db):
    # seeded account = never verified (1 stale account)
    _add_tx(seeded_db, primary_tag=None, days_ago=1)            # 1 uncategorized
    _add_import(seeded_db, source_name="voice", days_ago=9)     # 1 stale source

    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    assert out["attention_count"] == 3
    assert "generated_at" in out


# ─── Route wiring ──────────────────────────────────────────────────────────

from fastapi.testclient import TestClient  # noqa: E402
import app.main as app_main  # noqa: E402

client = TestClient(app_main.app)
client.cookies.set("hf_session", "x")


def test_health_data_endpoint_returns_json(monkeypatch):
    monkeypatch.setattr(app_main, "verify_session", lambda t: {"uid": "u", "hid": "h"})
    monkeypatch.setattr("app.api.routers.finance._use_rest", lambda: False)

    def fake(self, household_id, current_user_id=None):
        return {"attention_count": 0, "generated_at": "2026-05-28T00:00:00+00:00",
                "uncategorized": {"count": 0, "oldest_days": None, "status": "green", "items": []},
                "balances": {"status": "green", "accounts": []},
                "imports": {"status": "green", "sources": [], "last_activity_at": None},
                "people": [], "unassigned": []}

    monkeypatch.setattr(FinanceService, "data_health", fake)
    resp = client.get(
        "/finance/health/data?household_id=00000000-0000-0000-0000-000000000001",
    )
    assert resp.status_code == 200
    assert resp.json()["attention_count"] == 0


def test_health_page_renders(monkeypatch):
    monkeypatch.setattr(app_main, "verify_session", lambda t: {"uid": "u", "hid": "h"})
    monkeypatch.setattr("app.api.routers.finance._use_rest", lambda: False)

    def fake(self, household_id, current_user_id=None):
        return {"attention_count": 2, "generated_at": "2026-05-28T00:00:00+00:00",
                "uncategorized": {"count": 1, "oldest_days": 3, "status": "amber", "items": []},
                "balances": {"status": "red", "accounts": []},
                "imports": {"status": "green", "sources": [], "last_activity_at": None},
                "people": [], "unassigned": []}

    monkeypatch.setattr(FinanceService, "data_health", fake)
    resp = client.get(
        "/finance/health?household_id=00000000-0000-0000-0000-000000000001",
    )
    assert resp.status_code == 200
    assert "Состояние данных" in resp.text
