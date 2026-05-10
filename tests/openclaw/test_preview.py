import json
from datetime import date
from decimal import Decimal

from openclaw.normalizer import NormalizedRow
from openclaw.preview import render_preview, render_summary

HH_ID = "ed36b994-81e3-4fa0-b860-205381ba4681"


def _make_row(
    amount: Decimal | None = Decimal("350"),
    direction: str = "expense",
    currency: str = "RUB",
    merchant: str = "кафе",
    tag: str | None = None,
    parse_status: str = "ok",
    is_duplicate: bool = False,
) -> NormalizedRow:
    return NormalizedRow(
        raw_line="raw",
        date=date(2026, 3, 12),
        amount=amount,
        currency=currency,
        direction=direction,
        is_internal_transfer=False,
        is_planned=False,
        merchant_raw=merchant,
        description_raw=merchant,
        parse_status=parse_status,
        household_id=HH_ID,
        source="openclaw",
        occurred_at="2026-03-12T00:00:00+03:00",
        dedup_fingerprint="fp",
        primary_tag=tag,
        is_duplicate=is_duplicate,
    )


def test_preview_shows_counts(capsys):
    rows = [
        _make_row(),
        _make_row(is_duplicate=True),
        _make_row(parse_status="needs_correction", amount=None),
    ]
    render_preview(rows, force_duplicates=False)
    out = capsys.readouterr().out
    assert "1 new" in out
    assert "1 duplicate" in out
    assert "1 needs_correction" in out


def test_preview_shows_all_rows(capsys):
    rows = [_make_row(merchant="пятёрочка"), _make_row(merchant="такси", is_duplicate=True)]
    render_preview(rows, force_duplicates=False)
    out = capsys.readouterr().out
    assert "пятёрочка" in out
    assert "такси" in out


def test_preview_net_rub(capsys):
    rows = [
        _make_row(amount=Decimal("500"), direction="expense"),
        _make_row(amount=Decimal("90000"), direction="income"),
    ]
    render_preview(rows, force_duplicates=False)
    out = capsys.readouterr().out
    assert "89,500" in out or "89500" in out


def test_preview_omits_net_when_needs_correction(capsys):
    rows = [
        _make_row(amount=Decimal("500")),
        _make_row(amount=None, parse_status="needs_correction"),
    ]
    render_preview(rows, force_duplicates=False)
    out = capsys.readouterr().out
    assert "Net" not in out


def test_preview_json_mode(capsys):
    rows = [_make_row()]
    render_preview(rows, force_duplicates=False, json_output=True)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "rows" in data
    assert data["rows"][0]["merchant"] == "кафе"


def test_summary_shows_counts(capsys):
    render_summary(inserted_count=4, needs_correction_count=1, skipped_duplicates=1, ids=["id1", "id2"])
    out = capsys.readouterr().out
    assert "Inserted 4" in out
    assert "Needs correction: 1" in out
    assert "Skipped duplicates: 1" in out
    assert "id1" in out


def test_summary_json_mode(capsys):
    render_summary(4, 1, 1, ["id1"], json_output=True)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["inserted_count"] == 4
    assert data["ids"] == ["id1"]
