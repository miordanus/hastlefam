import httpx
import pytest
import respx

from openclaw.client import SupabaseClient, SupabaseError

BASE = "https://test.supabase.co"
KEY = "service-key"
HH_ID = "ed36b994-81e3-4fa0-b860-205381ba4681"


def make_client():
    return SupabaseClient(url=BASE, service_role_key=KEY, household_id=HH_ID)


@respx.mock
def test_get_sends_accept_profile():
    route = respx.get(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(200, json=[{"id": "abc"}])
    )
    client = make_client()
    result = client.get("transactions", params={"select": "id"})
    assert result == [{"id": "abc"}]
    assert route.called
    assert route.calls.last.request.headers["Accept-Profile"] == "hastlefam"


@respx.mock
def test_post_sends_content_profile():
    route = respx.post(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(201, json=[{"id": "xyz"}])
    )
    client = make_client()
    result = client.post("transactions", rows=[{"amount": 100}])
    assert result == [{"id": "xyz"}]
    assert route.called
    assert route.calls.last.request.headers["Content-Profile"] == "hastlefam"
    assert route.calls.last.request.headers["Prefer"] == "return=representation"


@respx.mock
def test_get_raises_on_non_2xx():
    respx.get(f"{BASE}/rest/v1/transactions").mock(
        return_value=httpx.Response(401, text="Unauthorized")
    )
    client = make_client()
    with pytest.raises(SupabaseError) as exc_info:
        client.get("transactions")
    assert exc_info.value.status_code == 401


def test_from_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", BASE)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", KEY)
    monkeypatch.setenv("HASTLEFAM_HOUSEHOLD_ID", HH_ID)
    client = SupabaseClient.from_env()
    assert client.household_id == HH_ID
