# OpenClaw Mass-Add Transactions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI tool (`python3 -m openclaw.mass_add`) that parses messy multiline transaction dumps, shows a preview, and bulk-inserts to Supabase after explicit confirmation.

**Architecture:** New `openclaw/` top-level package in the hastlefam repo (alongside `app/`). Six modules with clean single responsibilities: `client` → `parser` → `normalizer` → `dedup` → `preview` → `mass_add`. TDD throughout; respx mocks all httpx in tests.

**Tech Stack:** Python 3.12, httpx (sync), respx, pytest, Supabase REST (`hastlefam` schema), argparse, hashlib, dataclasses.

---

## Files

**Create:**
- `openclaw/__init__.py`
- `openclaw/client.py`
- `openclaw/parser.py`
- `openclaw/normalizer.py`
- `openclaw/dedup.py`
- `openclaw/preview.py`
- `openclaw/mass_add.py`
- `tests/openclaw/__init__.py`
- `tests/openclaw/test_client.py`
- `tests/openclaw/test_parser.py`
- `tests/openclaw/test_normalizer.py`
- `tests/openclaw/test_dedup.py`
- `tests/openclaw/test_preview.py`
- `tests/openclaw/test_mass_add.py`

**Modify:**
- `pyproject.toml` — add `httpx` to main deps, `respx` to test deps, add `openclaw*` to package discovery
- `README.md` — add OpenClaw mass-add usage section

---

### Task 0: Scaffolding — pyproject.toml + package dirs

**Files:**
- Modify: `pyproject.toml`
- Create: `openclaw/__init__.py`, `tests/openclaw/__init__.py`

- [ ] **Step 1: Update pyproject.toml**

Make these three changes to `pyproject.toml`:

```toml
[project]
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn>=0.30.0",
  "sqlalchemy>=2.0.36",
  "alembic>=1.13.3",
  "psycopg>=3.2.3",
  "psycopg-binary>=3.2.3",
  "pydantic>=2.10.0",
  "pydantic-settings>=2.6.1",
  "aiogram>=3.15.0",
  "openai>=1.54.0",
  "structlog>=24.4.0",
  "jinja2>=3.1.4",
  "python-multipart>=0.0.6",
  "apscheduler>=3.10",
  "redis>=5.0",
  "httpx>=0.27",
]

[project.optional-dependencies]
test = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "httpx>=0.27",
  "respx>=0.21",
]

[tool.setuptools.packages.find]
include = ["app*", "openclaw*"]
```

- [ ] **Step 2: Create package init files**

Create `openclaw/__init__.py` (empty):
```python
```

Create `tests/openclaw/__init__.py` (empty):
```python
```

- [ ] **Step 3: Install new deps**

```bash
pip install -e ".[test]"
```

Expected: installs without errors; `python -c "import respx; import httpx"` exits 0.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml openclaw/__init__.py tests/openclaw/__init__.py
git commit -m "chore: scaffold openclaw package and add httpx/respx deps"
```

---

### Task 1: SupabaseClient (`client.py`)

**Files:**
- Create: `openclaw/client.py`
- Create: `tests/openclaw/test_client.py`

- [ ] **Step 1: Write failing tests**

Create `tests/openclaw/test_client.py`:

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/openclaw/test_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'openclaw.client'`

- [ ] **Step 3: Implement `openclaw/client.py`**

```python
from __future__ import annotations
import os
import httpx


class SupabaseError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Supabase error {status_code}: {body}")


class SupabaseClient:
    def __init__(self, url: str, service_role_key: str, household_id: str) -> None:
        self.base_url = f"{url}/rest/v1"
        self.household_id = household_id
        self._client = httpx.Client(
            headers={
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

    @classmethod
    def from_env(cls) -> SupabaseClient:
        return cls(
            url=os.environ["SUPABASE_URL"],
            service_role_key=os.environ["SUPABASE_SERVICE_ROLE_KEY"],
            household_id=os.environ["HASTLEFAM_HOUSEHOLD_ID"],
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SupabaseClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
pytest tests/openclaw/test_client.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add openclaw/client.py tests/openclaw/test_client.py
git commit -m "feat(openclaw): add SupabaseClient with profile headers"
```

---

### Task 2: Transaction Parser (`parser.py`)

**Files:**
- Create: `openclaw/parser.py`
- Create: `tests/openclaw/test_parser.py`

- [ ] **Step 1: Write failing tests**

Create `tests/openclaw/test_parser.py`:

```python
from datetime import date
from decimal import Decimal

import pytest

from openclaw.parser import parse

TODAY = date(2026, 5, 10)


def test_rub_default():
    rows = parse("500 кафе", today=TODAY)
    assert len(rows) == 1
    assert rows[0].currency == "RUB"


def test_inline_usd():
    rows = parse("500 USD кафе", today=TODAY)
    assert rows[0].currency == "USD"


def test_inline_eur():
    rows = parse("20 EUR ресторан", today=TODAY)
    assert rows[0].currency == "EUR"


def test_plus_prefix_income():
    rows = parse("+90000 зп", today=TODAY)
    assert rows[0].direction == "income"
    assert rows[0].amount == Decimal("90000")


def test_income_keyword_zp():
    rows = parse("90000 зп", today=TODAY)
    assert rows[0].direction == "income"


def test_income_keyword_salary():
    rows = parse("90000 salary May", today=TODAY)
    assert rows[0].direction == "income"


def test_default_direction_expense():
    rows = parse("350 продукты", today=TODAY)
    assert rows[0].direction == "expense"
    assert rows[0].is_internal_transfer is False


def test_transfer_keyword():
    rows = parse("5000 перевод на карту", today=TODAY)
    assert rows[0].direction == "expense"
    assert rows[0].is_internal_transfer is True


def test_exchange_keyword():
    rows = parse("1000 exchange USD", today=TODAY)
    assert rows[0].direction == "exchange"


def test_vchera_date():
    rows = parse("500 кафе вчера", today=TODAY)
    assert rows[0].date == date(2026, 5, 9)


def test_pozavchera_date():
    rows = parse("500 кафе позавчера", today=TODAY)
    assert rows[0].date == date(2026, 5, 8)


def test_dd_mm_date():
    rows = parse("12.03 350 продукты", today=TODAY)
    assert rows[0].date == date(2026, 3, 12)


def test_dd_mm_dash_date():
    rows = parse("12-03 350 продукты", today=TODAY)
    assert rows[0].date == date(2026, 3, 12)


def test_yyyy_mm_dd_date():
    rows = parse("2026-03-12 350 продукты", today=TODAY)
    assert rows[0].date == date(2026, 3, 12)


def test_no_date_defaults_to_today():
    rows = parse("350 продукты", today=TODAY)
    assert rows[0].date == TODAY


def test_missing_amount_needs_correction():
    rows = parse("продукты пятёрочка", today=TODAY)
    assert rows[0].parse_status == "needs_correction"
    assert rows[0].amount is None
    assert len(rows) == 1  # never dropped


def test_ok_status_when_amount_present():
    rows = parse("350 продукты", today=TODAY)
    assert rows[0].parse_status == "ok"


def test_planned_suffix():
    rows = parse("500 кафе [planned]", today=TODAY)
    assert rows[0].is_planned is True


def test_slash_separator():
    rows = parse("12.03 350 продукты / 14.03 +90000 зп", today=TODAY)
    assert len(rows) == 2
    assert rows[0].direction == "expense"
    assert rows[0].amount == Decimal("350")
    assert rows[1].direction == "income"
    assert rows[1].amount == Decimal("90000")


def test_newline_separator():
    rows = parse("350 продукты\n+90000 зп", today=TODAY)
    assert len(rows) == 2


def test_merchant_raw_is_remainder():
    rows = parse("12.03 350 пятёрочка", today=TODAY)
    assert rows[0].merchant_raw == "пятёрочка"


def test_empty_lines_skipped():
    rows = parse("350 кафе\n\n500 такси", today=TODAY)
    assert len(rows) == 2


def test_decimal_amount():
    rows = parse("1499.99 подписка", today=TODAY)
    assert rows[0].amount == Decimal("1499.99")
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/openclaw/test_parser.py -v
```

Expected: `ModuleNotFoundError: No module named 'openclaw.parser'`

- [ ] **Step 3: Implement `openclaw/parser.py`**

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

INCOME_KEYWORDS: frozenset[str] = frozenset(
    {"зп", "зарплата", "доход", "refund", "salary", "income", "cashback"}
)
TRANSFER_KEYWORDS: frozenset[str] = frozenset({"перевод", "transfer"})
EXCHANGE_KEYWORDS: frozenset[str] = frozenset({"exchange", "обмен"})
CURRENCY_TOKENS: frozenset[str] = frozenset({"USD", "EUR", "AMD", "USDT"})

# DD.MM, DD-MM, DD/MM — but only when NOT preceded/followed by another digit
# (avoids matching YYYY-MM-DD fragments)
_DATE_SHORT = re.compile(r'(?<!\d)(\d{1,2})[.\-/](\d{1,2})(?!\d)')
_DATE_LONG = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
_AMOUNT_PLUS = re.compile(r'\+(\d+(?:[.,]\d+)?)')
_AMOUNT_BARE = re.compile(r'(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)')


@dataclass
class ParsedRow:
    raw_line: str
    date: date | None
    amount: Decimal | None
    currency: str
    direction: str
    is_internal_transfer: bool
    is_planned: bool
    merchant_raw: str
    description_raw: str
    parse_status: str


def _extract_date(text: str, today: date) -> tuple[date | None, str]:
    """Return (parsed_date, text_with_date_removed). Long form first to avoid partial match."""
    m = _DATE_LONG.search(text)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d, (text[: m.start()] + text[m.end() :]).strip()
        except ValueError:
            pass

    m = _DATE_SHORT.search(text)
    if m:
        try:
            d = date(today.year, int(m.group(2)), int(m.group(1)))
            return d, (text[: m.start()] + text[m.end() :]).strip()
        except ValueError:
            pass

    lower = text.lower()
    if "позавчера" in lower:
        return today - timedelta(days=2), re.sub("позавчера", "", text, flags=re.IGNORECASE).strip()
    if "вчера" in lower:
        return today - timedelta(days=1), re.sub("вчера", "", text, flags=re.IGNORECASE).strip()

    return None, text


def _parse_line(line: str, today: date) -> ParsedRow:
    remaining = line.strip()
    is_planned = False

    # [planned] flag — strip before anything else
    if re.search(r"\[planned\]", remaining, re.IGNORECASE):
        is_planned = True
        remaining = re.sub(r"\[planned\]", "", remaining, flags=re.IGNORECASE).strip()

    # Date
    parsed_date, remaining = _extract_date(remaining, today)
    if parsed_date is None:
        parsed_date = today

    # Future date + plan keyword
    lower = remaining.lower()
    if parsed_date > today and ("план" in lower or "plan" in lower):
        is_planned = True

    # Currency — remove token before amount extraction to avoid confusion
    currency = "RUB"
    for token in CURRENCY_TOKENS:
        if re.search(r"(?i)\b" + token + r"\b", remaining):
            currency = token.upper()
            remaining = re.sub(r"(?i)\b" + token + r"\b", "", remaining).strip()
            break

    # Amount — prefer +N form (income signal) over bare N
    amount: Decimal | None = None
    has_plus = False
    m = _AMOUNT_PLUS.search(remaining)
    if m:
        has_plus = True
        try:
            amount = Decimal(m.group(1).replace(",", "."))
        except InvalidOperation:
            pass
        remaining = (remaining[: m.start()] + remaining[m.end() :]).strip()
    else:
        m = _AMOUNT_BARE.search(remaining)
        if m:
            try:
                amount = Decimal(m.group(1).replace(",", "."))
            except InvalidOperation:
                pass
            remaining = (remaining[: m.start()] + remaining[m.end() :]).strip()

    # Direction — check keywords against what's left after amount extraction
    words = set(re.split(r"\W+", remaining.lower()))
    is_internal_transfer = False
    if has_plus or bool(words & INCOME_KEYWORDS):
        direction = "income"
        for kw in INCOME_KEYWORDS:
            remaining = re.sub(r"(?i)\b" + kw + r"\b", "", remaining).strip()
    elif bool(words & EXCHANGE_KEYWORDS):
        direction = "exchange"
        for kw in EXCHANGE_KEYWORDS:
            remaining = re.sub(r"(?i)\b" + kw + r"\b", "", remaining).strip()
    elif bool(words & TRANSFER_KEYWORDS):
        direction = "expense"
        is_internal_transfer = True
        for kw in TRANSFER_KEYWORDS:
            remaining = re.sub(r"(?i)\b" + kw + r"\b", "", remaining).strip()
    else:
        direction = "expense"

    merchant = re.sub(r"\s+", " ", remaining).strip(" ,;-")
    parse_status = "ok" if amount is not None else "needs_correction"

    return ParsedRow(
        raw_line=line,
        date=parsed_date,
        amount=amount,
        currency=currency,
        direction=direction,
        is_internal_transfer=is_internal_transfer,
        is_planned=is_planned,
        merchant_raw=merchant,
        description_raw=merchant,
        parse_status=parse_status,
    )


def parse(raw: str, today: date | None = None) -> list[ParsedRow]:
    """Parse a raw multiline / slash-separated transaction dump into ParsedRows."""
    if today is None:
        today = date.today()
    # Split on newlines OR " / " (space-slash-space) to avoid splitting DD/MM dates
    lines = re.split(r"\n| / ", raw)
    return [_parse_line(line, today) for line in lines if line.strip()]
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
pytest tests/openclaw/test_parser.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add openclaw/parser.py tests/openclaw/test_parser.py
git commit -m "feat(openclaw): add transaction parser (text → ParsedRow)"
```

---

### Task 3: Normalizer (`normalizer.py`)

**Files:**
- Create: `openclaw/normalizer.py`
- Create: `tests/openclaw/test_normalizer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/openclaw/test_normalizer.py`:

```python
import dataclasses
import hashlib
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from openclaw.normalizer import NormalizedRow, normalize, _compute_fingerprint
from openclaw.parser import ParsedRow

HH_ID = "ed36b994-81e3-4fa0-b860-205381ba4681"


def _make_client(tags: list[str] | None = None) -> MagicMock:
    client = MagicMock()
    client.household_id = HH_ID
    client.get.return_value = [{"primary_tag": t} for t in (tags or [])]
    return client


def _make_parsed(
    amount: Decimal | None = Decimal("350"),
    merchant: str = "пятёрочка",
    direction: str = "expense",
    d: date = date(2026, 3, 12),
    parse_status: str = "ok",
) -> ParsedRow:
    return ParsedRow(
        raw_line="raw",
        date=d,
        amount=amount,
        currency="RUB",
        direction=direction,
        is_internal_transfer=False,
        is_planned=False,
        merchant_raw=merchant,
        description_raw=merchant,
        parse_status=parse_status,
    )


def test_fingerprint_exact_format():
    fp = _compute_fingerprint(HH_ID, date(2026, 3, 12), Decimal("350"), "RUB", "пятёрочка", "expense")
    expected = hashlib.sha256(
        f"{HH_ID}|2026-03-12|350.00|RUB|пятёрочка|expense|openclaw".encode()
    ).hexdigest()
    assert fp == expected


def test_occurred_at_timezone():
    client = _make_client()
    rows = normalize([_make_parsed(d=date(2026, 3, 12))], client)
    assert rows[0].occurred_at == "2026-03-12T00:00:00+03:00"


def test_source_is_always_openclaw():
    client = _make_client()
    rows = normalize([_make_parsed()], client)
    assert rows[0].source == "openclaw"


def test_household_id_from_client():
    client = _make_client()
    rows = normalize([_make_parsed()], client)
    assert rows[0].household_id == HH_ID


def test_known_tag_exact_match():
    client = _make_client(tags=["groceries", "пятёрочка"])
    rows = normalize([_make_parsed(merchant="пятёрочка")], client)
    assert rows[0].primary_tag == "пятёрочка"


def test_tag_match_case_insensitive():
    client = _make_client(tags=["пятёрочка"])
    rows = normalize([_make_parsed(merchant="ПЯТЁРОЧКА")], client)
    assert rows[0].primary_tag == "пятёрочка"


def test_no_tag_match():
    client = _make_client(tags=["groceries"])
    rows = normalize([_make_parsed(merchant="кафе рандом")], client)
    assert rows[0].primary_tag is None


def test_none_amount_no_fingerprint():
    client = _make_client()
    rows = normalize([_make_parsed(amount=None, parse_status="needs_correction")], client)
    assert rows[0].dedup_fingerprint is None


def test_none_date_uses_today(monkeypatch):
    import openclaw.normalizer as mod
    fixed = date(2026, 5, 10)
    monkeypatch.setattr(mod, "_today", lambda: fixed)
    client = _make_client()
    row = dataclasses.replace(_make_parsed(), date=None)
    rows = normalize([row], client)
    assert rows[0].occurred_at == "2026-05-10T00:00:00+03:00"


def test_is_duplicate_defaults_false():
    client = _make_client()
    rows = normalize([_make_parsed()], client)
    assert rows[0].is_duplicate is False


def test_tag_fetch_called_once_for_multiple_rows():
    client = _make_client(tags=["groceries"])
    normalize([_make_parsed(), _make_parsed(merchant="такси")], client)
    assert client.get.call_count == 1
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/openclaw/test_normalizer.py -v
```

Expected: `ModuleNotFoundError: No module named 'openclaw.normalizer'`

- [ ] **Step 3: Implement `openclaw/normalizer.py`**

```python
from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from openclaw.client import SupabaseClient
from openclaw.parser import ParsedRow


def _today() -> date:
    return date.today()


@dataclass
class NormalizedRow:
    # ParsedRow fields (duplicated to avoid dataclass inheritance ordering issues)
    raw_line: str
    date: date | None
    amount: Decimal | None
    currency: str
    direction: str
    is_internal_transfer: bool
    is_planned: bool
    merchant_raw: str
    description_raw: str
    parse_status: str
    # Normalizer-added fields
    household_id: str
    source: str
    occurred_at: str
    dedup_fingerprint: str | None
    primary_tag: str | None
    is_duplicate: bool


def _compute_fingerprint(
    household_id: str,
    d: date,
    amount: Decimal,
    currency: str,
    merchant: str,
    direction: str,
) -> str:
    raw = f"{household_id}|{d}|{amount:.2f}|{currency}|{merchant.lower()}|{direction}|openclaw"
    return hashlib.sha256(raw.encode()).hexdigest()


def _fetch_known_tags(client: SupabaseClient) -> set[str]:
    rows = client.get(
        "transactions",
        params={
            "select": "primary_tag",
            "household_id": f"eq.{client.household_id}",
            "primary_tag": "not.is.null",
            "limit": "200",
        },
    )
    return {r["primary_tag"].lower() for r in rows if r.get("primary_tag")}


def normalize(rows: list[ParsedRow], client: SupabaseClient) -> list[NormalizedRow]:
    known_tags = _fetch_known_tags(client)
    today = _today()

    result: list[NormalizedRow] = []
    for row in rows:
        d = row.date if row.date is not None else today
        occurred_at = f"{d.isoformat()}T00:00:00+03:00"

        fingerprint: str | None = None
        if row.amount is not None:
            fingerprint = _compute_fingerprint(
                client.household_id, d, row.amount, row.currency,
                row.merchant_raw, row.direction,
            )

        merchant_lower = row.merchant_raw.lower()
        primary_tag = merchant_lower if merchant_lower in known_tags else None

        result.append(
            NormalizedRow(
                raw_line=row.raw_line,
                date=row.date,
                amount=row.amount,
                currency=row.currency,
                direction=row.direction,
                is_internal_transfer=row.is_internal_transfer,
                is_planned=row.is_planned,
                merchant_raw=row.merchant_raw,
                description_raw=row.description_raw,
                parse_status=row.parse_status,
                household_id=client.household_id,
                source="openclaw",
                occurred_at=occurred_at,
                dedup_fingerprint=fingerprint,
                primary_tag=primary_tag,
                is_duplicate=False,
            )
        )
    return result
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/openclaw/test_normalizer.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add openclaw/normalizer.py tests/openclaw/test_normalizer.py
git commit -m "feat(openclaw): add normalizer (household_id, fingerprint, tags, occurred_at)"
```

---

### Task 4: Dedup check (`dedup.py`)

**Files:**
- Create: `openclaw/dedup.py`
- Create: `tests/openclaw/test_dedup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/openclaw/test_dedup.py`:

```python
import dataclasses
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from openclaw.dedup import check
from openclaw.normalizer import NormalizedRow

HH_ID = "ed36b994-81e3-4fa0-b860-205381ba4681"


def _make_row(fp: str | None = "abc123", is_duplicate: bool = False) -> NormalizedRow:
    return NormalizedRow(
        raw_line="raw",
        date=date(2026, 3, 12),
        amount=Decimal("350"),
        currency="RUB",
        direction="expense",
        is_internal_transfer=False,
        is_planned=False,
        merchant_raw="кафе",
        description_raw="кафе",
        parse_status="ok",
        household_id=HH_ID,
        source="openclaw",
        occurred_at="2026-03-12T00:00:00+03:00",
        dedup_fingerprint=fp,
        primary_tag=None,
        is_duplicate=is_duplicate,
    )


def test_marks_duplicate_when_fingerprint_found():
    client = MagicMock()
    client.get.return_value = [{"id": "existing-uuid"}]
    rows = check([_make_row(fp="abc123")], client)
    assert rows[0].is_duplicate is True


def test_not_duplicate_when_no_match():
    client = MagicMock()
    client.get.return_value = []
    rows = check([_make_row(fp="abc123")], client)
    assert rows[0].is_duplicate is False


def test_no_check_when_fingerprint_is_none():
    client = MagicMock()
    rows = check([_make_row(fp=None)], client)
    assert rows[0].is_duplicate is False
    client.get.assert_not_called()


def test_get_called_with_correct_params():
    client = MagicMock()
    client.get.return_value = []
    check([_make_row(fp="myfp")], client)
    client.get.assert_called_once_with(
        "transactions",
        params={"dedup_fingerprint": "eq.myfp", "select": "id", "limit": "1"},
    )


def test_multiple_rows_checked_sequentially():
    client = MagicMock()
    client.get.side_effect = [[{"id": "x"}], []]
    rows = check([_make_row(fp="fp1"), _make_row(fp="fp2")], client)
    assert rows[0].is_duplicate is True
    assert rows[1].is_duplicate is False
    assert client.get.call_count == 2
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/openclaw/test_dedup.py -v
```

Expected: `ModuleNotFoundError: No module named 'openclaw.dedup'`

- [ ] **Step 3: Implement `openclaw/dedup.py`**

```python
from __future__ import annotations

import dataclasses

from openclaw.client import SupabaseClient
from openclaw.normalizer import NormalizedRow


def check(rows: list[NormalizedRow], client: SupabaseClient) -> list[NormalizedRow]:
    """Check each row's dedup_fingerprint against the DB. Returns rows with is_duplicate set."""
    result: list[NormalizedRow] = []
    for row in rows:
        if row.dedup_fingerprint is None:
            result.append(row)
            continue
        existing = client.get(
            "transactions",
            params={
                "dedup_fingerprint": f"eq.{row.dedup_fingerprint}",
                "select": "id",
                "limit": "1",
            },
        )
        if existing:
            row = dataclasses.replace(row, is_duplicate=True)
        result.append(row)
    return result
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/openclaw/test_dedup.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add openclaw/dedup.py tests/openclaw/test_dedup.py
git commit -m "feat(openclaw): add dedup pre-check against Supabase fingerprints"
```

---

### Task 5: Preview renderer (`preview.py`)

**Files:**
- Create: `openclaw/preview.py`
- Create: `tests/openclaw/test_preview.py`

- [ ] **Step 1: Write failing tests**

Create `tests/openclaw/test_preview.py`:

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/openclaw/test_preview.py -v
```

Expected: `ModuleNotFoundError: No module named 'openclaw.preview'`

- [ ] **Step 3: Implement `openclaw/preview.py`**

```python
from __future__ import annotations

import json
from decimal import Decimal

from openclaw.normalizer import NormalizedRow

_SEP = "─" * 72


def _status_symbol(row: NormalizedRow) -> str:
    if row.is_duplicate:
        return "duplicate ⟳"
    if row.parse_status == "needs_correction":
        return "⚠ needs_correction"
    return "✓"


def _net_by_currency(rows: list[NormalizedRow]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        if row.is_duplicate or row.amount is None:
            continue
        sign = Decimal("-1") if row.direction == "expense" else Decimal("1")
        if row.direction == "exchange":
            continue
        totals[row.currency] = totals.get(row.currency, Decimal("0")) + sign * row.amount
    return totals


def render_preview(
    rows: list[NormalizedRow],
    force_duplicates: bool = False,
    json_output: bool = False,
) -> None:
    n_new = sum(1 for r in rows if not r.is_duplicate)
    n_dup = sum(1 for r in rows if r.is_duplicate)
    n_corr = sum(1 for r in rows if r.parse_status == "needs_correction" and not r.is_duplicate)

    if json_output:
        data = {
            "summary": {"new": n_new, "duplicate": n_dup, "needs_correction": n_corr},
            "rows": [
                {
                    "index": i + 1,
                    "date": str(r.date) if r.date else None,
                    "direction": r.direction,
                    "amount": float(r.amount) if r.amount is not None else None,
                    "currency": r.currency,
                    "merchant": r.merchant_raw,
                    "tag": r.primary_tag,
                    "status": "duplicate" if r.is_duplicate else r.parse_status,
                }
                for i, r in enumerate(rows)
            ],
        }
        print(json.dumps(data, ensure_ascii=False))
        return

    print("OpenClaw — mass add preview")
    print(f"{n_new} new  |  {n_dup} duplicate  |  {n_corr} needs_correction")
    print(_SEP)
    print(f"  {'#':>3}  {'date':<12} {'dir':<8} {'amount':>10}  {'cur':<5} {'merchant':<20} {'tag':<12} status")

    for i, row in enumerate(rows):
        amt = f"{row.amount:>10.2f}" if row.amount is not None else f"{'???':>10}"
        date_str = str(row.date) if row.date else "???"
        tag_str = (row.primary_tag or "")[:12]
        merchant_str = row.merchant_raw[:20]
        status = _status_symbol(row)
        print(f"  {i + 1:>3}  {date_str:<12} {row.direction:<8} {amt}  {row.currency:<5} {merchant_str:<20} {tag_str:<12} {status}")

    print(_SEP)

    # Net — only if no needs_correction rows with unknown amount in the new set
    new_rows = [r for r in rows if not r.is_duplicate]
    has_unknown_amount = any(r.amount is None for r in new_rows)
    if not has_unknown_amount:
        net = _net_by_currency(rows)
        for cur, total in net.items():
            sign = "+" if total >= 0 else ""
            print(f"Net new ({cur}): {sign}{total:,.2f}")


def render_summary(
    inserted_count: int,
    needs_correction_count: int,
    skipped_duplicates: int,
    ids: list[str],
    json_output: bool = False,
) -> None:
    if json_output:
        print(json.dumps({
            "inserted_count": inserted_count,
            "needs_correction_count": needs_correction_count,
            "skipped_duplicates_count": skipped_duplicates,
            "ids": ids,
        }))
        return
    print(f"Inserted {inserted_count} | Needs correction: {needs_correction_count} | Skipped duplicates: {skipped_duplicates}")
    if ids:
        print(f"IDs: {ids}")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/openclaw/test_preview.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add openclaw/preview.py tests/openclaw/test_preview.py
git commit -m "feat(openclaw): add preview renderer (table + summary, text + JSON)"
```

---

### Task 6: CLI entry point (`mass_add.py`)

**Files:**
- Create: `openclaw/mass_add.py`
- Create: `tests/openclaw/test_mass_add.py`

- [ ] **Step 1: Write failing tests**

Create `tests/openclaw/test_mass_add.py`:

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/openclaw/test_mass_add.py -v
```

Expected: `ModuleNotFoundError: No module named 'openclaw.mass_add'`

- [ ] **Step 3: Implement `openclaw/mass_add.py`**

```python
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from openclaw.client import SupabaseClient, SupabaseError
from openclaw.dedup import check as dedup_check
from openclaw.normalizer import NormalizedRow, normalize
from openclaw.parser import parse
from openclaw.preview import render_preview, render_summary


def _to_insert_dict(row: NormalizedRow) -> dict:
    d: dict = {
        "household_id": row.household_id,
        "direction": row.direction,
        "amount": float(row.amount) if row.amount is not None else None,
        "currency": row.currency,
        "occurred_at": row.occurred_at,
        "source": row.source,
        "parse_status": row.parse_status,
        "merchant_raw": row.merchant_raw,
        "description_raw": row.description_raw,
        "is_planned": row.is_planned,
        "is_internal_transfer": row.is_internal_transfer,
    }
    if row.dedup_fingerprint:
        d["dedup_fingerprint"] = row.dedup_fingerprint
    if row.primary_tag:
        d["primary_tag"] = row.primary_tag
    return d


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OpenClaw mass-add: parse → preview → confirm → bulk insert to Supabase"
    )
    parser.add_argument("text", nargs="?", help="Transaction text (or omit to read from stdin)")
    parser.add_argument("--confirm", action="store_true", help="Skip interactive confirmation prompt")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Output JSON instead of tables")
    parser.add_argument("--force-duplicates", action="store_true", help="Insert duplicate-fingerprint rows too")
    args = parser.parse_args(argv)

    raw = args.text if args.text else sys.stdin.read()
    if not raw.strip():
        print("Error: no input provided.", file=sys.stderr)
        return 1

    try:
        with SupabaseClient.from_env() as client:
            parsed_rows = parse(raw)
            normalized_rows = normalize(parsed_rows, client)
            deduped_rows = dedup_check(normalized_rows, client)

            render_preview(deduped_rows, force_duplicates=args.force_duplicates, json_output=args.json_output)

            if not args.confirm:
                answer = input("Proceed? [y/N] ").strip().lower()
                if answer not in ("y", "yes"):
                    print("Cancelled.")
                    return 0

            insertable = [
                r for r in deduped_rows
                if not r.is_duplicate or args.force_duplicates
            ]

            if not insertable:
                render_summary(0, 0, sum(1 for r in deduped_rows if r.is_duplicate), [], json_output=args.json_output)
                return 0

            inserted = client.post("transactions", rows=[_to_insert_dict(r) for r in insertable])
            ids = [str(r.get("id", "")) for r in inserted]

            needs_correction_count = sum(1 for r in insertable if r.parse_status == "needs_correction")
            skipped = sum(1 for r in deduped_rows if r.is_duplicate and not args.force_duplicates)

            render_summary(len(ids), needs_correction_count, skipped, ids, json_output=args.json_output)

    except SupabaseError as e:
        print(f"Supabase error {e.status_code}: {e.body}", file=sys.stderr)
        return 1
    except KeyError as e:
        print(f"Missing env var: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/openclaw/test_mass_add.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest tests/ -v --tb=short
```

Expected: all openclaw tests pass; existing app tests unaffected.

- [ ] **Step 6: Commit**

```bash
git add openclaw/mass_add.py tests/openclaw/test_mass_add.py
git commit -m "feat(openclaw): add mass_add CLI — parse/preview/confirm/bulk-insert"
```

---

### Task 7: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add OpenClaw section to README.md**

Append the following section to `README.md` after the existing Quick start section:

```markdown
## OpenClaw — mass add transactions

CLI tool for bulk-adding transactions from voice transcriptions or text dumps.

### Setup

Set env vars (in addition to the existing `DATABASE_URL` etc.):
```bash
export SUPABASE_URL=https://<ref>.supabase.co
export SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
export HASTLEFAM_HOUSEHOLD_ID=ed36b994-81e3-4fa0-b860-205381ba4681
```

### Usage

```bash
# Single-line or slash-separated
python3 -m openclaw.mass_add "12.03 350 продукты / 14.03 +90000 зп"

# Multiline via stdin
cat transactions.txt | python3 -m openclaw.mass_add

# Skip confirmation prompt (for agent/script use)
python3 -m openclaw.mass_add "350 кафе" --confirm

# Machine-readable JSON output
python3 -m openclaw.mass_add "350 кафе" --confirm --json

# Include duplicate-fingerprint rows (normally skipped)
python3 -m openclaw.mass_add "350 кафе" --confirm --force-duplicates
```

### Input format

One transaction per line (or separated by ` / `). Each line:
- Optional date: `DD.MM`, `DD-MM`, `DD/MM`, `YYYY-MM-DD`, `вчера`, `позавчера` (defaults to today)
- Amount: bare number or `+N` (+ marks income)
- Optional currency: `USD`, `EUR`, `AMD`, `USDT` (defaults to `RUB`)
- Income keywords: `зп`, `зарплата`, `доход`, `salary`, `income`
- Transfer keyword: `перевод`, `transfer` → sets `is_internal_transfer=true`
- Remainder: merchant description
- `[planned]` suffix → marks as planned (not actual spend)

Rows that can't be parsed get `parse_status=needs_correction` and are shown in the preview but still inserted — never silently dropped.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add OpenClaw mass-add usage to README"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Input parser (multiline, slash-separated, voice dump format) — Task 2
- ✅ All required fields (household_id, direction, amount, currency, occurred_at, source, parse_status, dedup_fingerprint, merchant_raw, description_raw, is_planned, is_internal_transfer) — Tasks 3 + 6
- ✅ Dedup pre-check + flag in preview + skip on insert — Tasks 4 + 6
- ✅ Preview (count summary + per-row table) — Task 5
- ✅ Confirmation gate (interactive + --confirm flag) — Task 6
- ✅ Post-insert summary (inserted/needs_correction/skipped + IDs) — Tasks 5 + 6
- ✅ --json output mode — Tasks 5 + 6
- ✅ --force-duplicates flag — Tasks 5 + 6
- ✅ source="openclaw" verified in tests — Task 6
- ✅ README updated — Task 7
- ✅ All hard constraints (no DELETE, no writes without confirmation, direction/currency/tag casing) — enforced throughout
- ✅ Unit tests for parser — Task 2
- ✅ Mock Supabase REST in all tests — Tasks 1, 3, 4, 6
