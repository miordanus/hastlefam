from __future__ import annotations
import os
import httpx


class SupabaseError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Supabase error {status_code}: {body}")


class SupabaseClient:
    def __init__(self, url: str, service_role_key: str, household_id: str | None = None) -> None:
        self.base_url = f"{url}/rest/v1"
        self.household_id = household_id
        self._client = httpx.Client(
            headers={
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def get(self, table: str, params: dict | None = None) -> list[dict]:
        resp = self._client.get(
            f"{self.base_url}/{table}",
            params=params,
            headers={"Accept-Profile": "hastlefam"},
        )
        if resp.status_code >= 300:
            raise SupabaseError(resp.status_code, resp.text)
        return resp.json()

    def post(self, table: str, rows: list[dict]) -> list[dict]:
        resp = self._client.post(
            f"{self.base_url}/{table}",
            json=rows,
            headers={
                "Content-Profile": "hastlefam",
                "Prefer": "return=representation",
            },
        )
        if resp.status_code >= 300:
            raise SupabaseError(resp.status_code, resp.text)
        return resp.json()

    def patch(self, table: str, params: dict, body: dict) -> list[dict]:
        resp = self._client.patch(
            f"{self.base_url}/{table}",
            params=params,
            json=body,
            headers={
                "Content-Profile": "hastlefam",
                "Prefer": "return=representation",
            },
        )
        if resp.status_code >= 300:
            raise SupabaseError(resp.status_code, resp.text)
        return resp.json()

    def rpc(self, fn_name: str, args: dict) -> list[dict]:
        resp = self._client.post(
            f"{self.base_url}/rpc/{fn_name}",
            json=args,
            headers={"Content-Profile": "hastlefam"},
        )
        if resp.status_code >= 300:
            raise SupabaseError(resp.status_code, resp.text)
        return resp.json()

    @classmethod
    def from_env(cls) -> SupabaseClient:
        return cls(
            url=os.environ["SUPABASE_URL"],
            service_role_key=os.environ["SUPABASE_SERVICE_ROLE_KEY"],
            household_id=os.environ.get("HASTLEFAM_HOUSEHOLD_ID"),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SupabaseClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
