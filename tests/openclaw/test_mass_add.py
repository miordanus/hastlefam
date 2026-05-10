import json
import sys

import httpx
import pytest
import respx

from openclaw.mass_add import main

BASE = "https://test.supabase.co"
HH_ID = "ed36b994-81e3-4fa0-b860-205381ba4681"


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", BASE)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("HASTLEFAM_HOUSEHOLD_ID", HH_ID)


@respx.mock
def test_source_openclaw_in_every_inserted_row():
    """Every row POSTed must have source='openclaw'."""
    respx.get(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(200, json=[])
    )
    post_route = respx.post(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(201, json=[{"id": "uuid-1", "source": "openclaw"}])
    )
    main(["350 продукты", "--confirm"])
    body = json.loads(post_route.calls.last.request.content)
    assert all(row["source"] == "openclaw" for row in body)


@respx.mock
def test_duplicate_skipped_by_default():
    """Row with matching fingerprint is not included in POST."""
    # First GET = tag fetch (returns empty)
    # Subsequent GETs = dedup check (returns existing row = duplicate)
    get_route = respx.get(f"{BASE}/rest/v1/transactions").mock(
        side_effect=[
            httpx.Response(200, json=[]),          # tag fetch
            httpx.Response(200, json=[{"id": "existing"}]),  # dedup check
        ]
    )
    post_route = respx.post(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(201, json=[])
    )
    main(["350 продукты", "--confirm"])
    # POST should not be called (all rows are duplicates)
    assert not post_route.called


@respx.mock
def test_force_duplicates_includes_duplicate_row():
    """--force-duplicates includes duplicate rows in POST."""
    respx.get(f"{BASE}/rest/v1/transactions").mock(
        side_effect=[
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[{"id": "existing"}]),
        ]
    )
    post_route = respx.post(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(201, json=[{"id": "new-id", "source": "openclaw"}])
    )
    main(["350 продукты", "--confirm", "--force-duplicates"])
    assert post_route.called


@respx.mock
def test_needs_correction_rows_included_in_post():
    """Rows with parse_status=needs_correction are inserted, not dropped."""
    respx.get(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(200, json=[])
    )
    post_route = respx.post(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(201, json=[{"id": "uuid-1", "source": "openclaw"}])
    )
    # "продукты" with no amount → needs_correction
    main(["продукты пятёрочка", "--confirm"])
    assert post_route.called
    body = json.loads(post_route.calls.last.request.content)
    assert body[0]["parse_status"] == "needs_correction"


@respx.mock
def test_no_post_without_confirm(monkeypatch):
    """Without --confirm, no POST unless interactive 'y' is given."""
    respx.get(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(200, json=[])
    )
    post_route = respx.post(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(201, json=[])
    )
    # Simulate user typing 'n' at the prompt
    monkeypatch.setattr("builtins.input", lambda _: "n")
    main(["350 продукты"])
    assert not post_route.called


@respx.mock
def test_json_output_mode(capsys):
    """--json flag produces parseable JSON output."""
    respx.get(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.post(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(201, json=[{"id": "uuid-1", "source": "openclaw"}])
    )
    main(["350 продукты", "--confirm", "--json"])
    out = capsys.readouterr().out
    # Output should be two JSON blobs (preview + summary) — just check it's valid JSON lines
    lines = [l for l in out.strip().splitlines() if l.strip()]
    for line in lines:
        json.loads(line)  # must not raise


@respx.mock
def test_all_required_fields_in_post_body():
    """POST body must include all required fields per operational contract."""
    respx.get(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(200, json=[])
    )
    post_route = respx.post(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(201, json=[{"id": "uuid-1"}])
    )
    main(["350 продукты", "--confirm"])
    body = json.loads(post_route.calls.last.request.content)
    row = body[0]
    required = {
        "household_id", "direction", "amount", "currency", "occurred_at",
        "source", "parse_status", "merchant_raw", "description_raw",
        "is_planned", "is_internal_transfer",
    }
    for field in required:
        assert field in row, f"Missing required field: {field}"
