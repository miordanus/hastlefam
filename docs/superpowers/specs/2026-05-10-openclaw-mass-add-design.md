# OpenClaw Mass-Add Transactions — Design Spec

**Date:** 2026-05-10
**Repo:** hastlefam (new `openclaw/` top-level package)
**Branch:** openclaw/mass-add-transactions

---

## Goal

Replace manual Telegram transaction entry with a batched CLI tool: paste or pipe a messy multiline dump of expenses/incomes, get a preview table, confirm, bulk-insert into Supabase. Primary pain-killer for the household.

---

## Context

- OpenClaw is a Python agent running on a VPS that talks directly to Supabase REST (bypassing FastAPI)
- DB schema: `hastlefam` on Supabase project `sfzyqdpckgyznuhunygj`
- All reads use `Accept-Profile: hastlefam`; all writes use `Content-Profile: hastlefam`
- `SUPABASE_SERVICE_ROLE_KEY` and `SUPABASE_URL` are env vars
- `HASTLEFAM_HOUSEHOLD_ID = ed36b994-81e3-4fa0-b860-205381ba4681`
- Python 3.12.3 on VPS; sync `httpx`; `pytest` + `respx` for tests
- Operational contract: `docs/openclaw-agent-instructions.md`

---

## Architecture

New top-level package `openclaw/` in the hastlefam repo — separate from `app/` (FastAPI/bot layer). Same `pyproject.toml`, same test runner.

### File layout

```
openclaw/
  __init__.py
  client.py       ← httpx sync Supabase REST client; profile headers; env config
  parser.py       ← raw text → list[ParsedRow]; pure, no I/O
  normalizer.py   ← fill required fields, resolve tags, compute fingerprint
  dedup.py        ← pre-check fingerprints against existing DB rows via REST
  preview.py      ← render preview table + post-insert summary to stdout
  mass_add.py     ← CLI entry point; orchestrates full flow

tests/openclaw/
  __init__.py
  test_parser.py       ← pure unit tests
  test_normalizer.py   ← unit tests for fingerprint, tag match, parse_status
  test_mass_add.py     ← integration with respx-mocked httpx
```

### CLI invocation

```bash
# positional arg
python3 -m openclaw.mass_add "12.03 350 продукты / 14.03 +90000 зп"

# stdin pipe
echo "..." | python3 -m openclaw.mass_add

# flags
--confirm          skip interactive prompt (for agent/non-interactive use)
--json             machine-readable JSON output instead of table
--force-duplicates include duplicate rows in insert (default: skip)
```

---

## Module Design

### `client.py`

Thin wrapper around `httpx.Client`. Constructed once per CLI run.

```python
SupabaseClient(url, service_role_key, household_id)
  .get(table, params) -> list[dict]
  .post(table, rows)  -> list[dict]   # Prefer: return=representation
```

Headers injected automatically:
- `Authorization: Bearer {key}`
- `Accept-Profile: hastlefam` (GET)
- `Content-Profile: hastlefam` (POST)
- `Content-Type: application/json`
- `Prefer: return=representation` (POST only)

Raises `SupabaseError` on non-2xx. No retry logic.

---

### `parser.py`

**Input:** raw string (newline or `/`-separated lines)
**Output:** `list[ParsedRow]`

`ParsedRow` is a dataclass:
```python
@dataclass
class ParsedRow:
    raw_line: str
    date: date | None          # None → parse_status=needs_correction
    amount: Decimal | None     # None → parse_status=needs_correction
    currency: str              # RUB default
    direction: str             # expense | income | exchange
    is_internal_transfer: bool
    is_planned: bool
    merchant_raw: str
    description_raw: str
    parse_status: str          # "ok" | "needs_correction"
```

**Parsing order per line:**
1. **Split** on `\n` and `/`; strip whitespace; skip empty lines
2. **Date** — scan for tokens matching: `DD.MM`, `DD-MM`, `DD/MM`, `YYYY-MM-DD`, `вчера` (yesterday), `позавчера` (day before yesterday). If no date found, default to today `+03:00`. Future date + `план`/`plan` keyword → `is_planned=True`
3. **Amount** — first bare integer or decimal; if absent → `parse_status="needs_correction"`
4. **Currency** — inline token `USD`/`EUR`/`AMD`/`USDT` (case-insensitive); default `RUB`. Stored uppercase.
5. **Direction** — `+` prefix on amount OR income keywords (`зп`, `зарплата`, `доход`, `refund`, `salary`, `income`, `cashback`) → `income`; transfer keywords (`перевод`, `transfer`) → `expense` + `is_internal_transfer=True`; explicit keyword `exchange`/`обмен` → `exchange`; else `expense`. Stored lowercase.
6. **Merchant** — remainder after stripping date/amount/currency/direction tokens; strip punctuation; default `""` (does not trigger needs_correction alone)
7. **`[planned]`** suffix anywhere on line → `is_planned=True`

Parser is pure (no I/O, no env vars). All edge cases produce a row with `parse_status="needs_correction"` — never silently dropped.

---

### `normalizer.py`

**Input:** `list[ParsedRow]`, `SupabaseClient`
**Output:** `list[NormalizedRow]`

`NormalizedRow` extends `ParsedRow` with:
```python
household_id: str
source: str              # always "openclaw"
occurred_at: str         # ISO 8601 with +03:00; today T00:00:00+03:00 if date was None
dedup_fingerprint: str
primary_tag: str | None
is_duplicate: bool       # filled by dedup.py; default False
```

**Tag resolution (once per session):**
```
GET /transactions
  ?select=primary_tag
  &household_id=eq.{id}
  &primary_tag=not.is.null
  &limit=200
```
Deduplicate → `known_tags: set[str]` (all lowercase). Match `merchant_raw.lower()` against known tags: exact match only. No fuzzy. If no match → `primary_tag=None`.

**Fingerprint:**
```python
sha256(f"{household_id}|{date}|{amount}|{currency}|{merchant_lower}|{direction}|openclaw")
```

**`occurred_at`:** date from parser formatted as `{date}T00:00:00+03:00`.

---

### `dedup.py`

**Input:** `list[NormalizedRow]`, `SupabaseClient`
**Output:** `list[NormalizedRow]` with `is_duplicate: bool` field added

For each row, GET:
```
GET /transactions?dedup_fingerprint=eq.{fp}&select=id&limit=1
Headers: Accept-Profile: hastlefam
```

Rows with a result → `is_duplicate=True`. Requests run sequentially (one per row). No bulk fingerprint query (PostgREST `in.` filter would work but sequential keeps it simple and safe).

---

### `preview.py`

Two functions:

**`render_preview(rows, force_duplicates)`** → prints to stdout:
```
OpenClaw — mass add preview
{n_new} new  |  {n_dup} duplicate  |  {n_corr} needs_correction
──────────────────────────────────────────────────────────────────
  #  date        dir      amount      cur   merchant          tag        status
  1  2026-03-12  expense     350.00   RUB   пятёрочка         groceries  ✓
  2  2026-03-14  income   90000.00   RUB   зп                            ✓
  4  2026-03-10  expense    1200.00   RUB   такси             transport  duplicate ⟳
  5  2026-03-15  expense       ???   RUB   неизвестно                    ⚠ needs_correction
──────────────────────────────────────────────────────────────────
Net new (RUB): +89,650.00
```

Net shown per-currency if mixed; omitted if any `needs_correction` row is in the new set (amount unknown).

**`render_summary(result)`** → prints post-insert summary:
```
Inserted 4 | Needs correction: 1 | Skipped duplicates: 1
IDs: [uuid1, uuid2, uuid3, uuid4]
```

With `--json`: both functions emit structured JSON to stdout instead.

---

### `mass_add.py`

CLI entry point (`__main__` block + `main()` function).

**Flow:**
1. Parse CLI args (`argparse`): input text (positional or stdin), `--confirm`, `--json`, `--force-duplicates`
2. Construct `SupabaseClient` from env vars
3. Call `parser.parse(raw_text)` → `list[ParsedRow]`
4. Call `normalizer.normalize(rows, client)` → `list[NormalizedRow]`
5. Call `dedup.check(rows, client)` → rows with `is_duplicate` flag
6. Call `preview.render_preview(rows, force_duplicates=...)`
7. If not `--confirm`: prompt `Proceed? [y/N]`; exit 0 on N
8. Filter to insertable rows (non-duplicate, or all if `--force-duplicates`)
9. Bulk POST to `/transactions` — all required fields per operational contract
10. Call `preview.render_summary(result)`
11. Exit 0

**Exit codes:** 0 = success or user cancelled; 1 = error (auth failure, parse total failure, etc.)

---

## Required Fields on Every INSERT

Per operational contract (`docs/openclaw-agent-instructions.md`):

| Field | Value |
|---|---|
| `household_id` | `HASTLEFAM_HOUSEHOLD_ID` env var |
| `direction` | `expense` / `income` / `exchange` |
| `amount` | Decimal, 2dp |
| `currency` | uppercase string |
| `occurred_at` | ISO 8601, `+03:00` |
| `source` | `"openclaw"` |
| `parse_status` | `"ok"` or `"needs_correction"` |
| `dedup_fingerprint` | SHA-256 string |
| `merchant_raw` | raw merchant string |
| `description_raw` | same as merchant_raw |
| `is_planned` | bool, default `False` |
| `is_internal_transfer` | bool, default `False` |

`account_id` stays `null` (out of scope per spec).

---

## Hard Constraints

- No DELETE operations
- No schema changes
- No writes without explicit user confirmation (`--confirm` flag or interactive `y`)
- Tags always stored lowercased
- `direction` stored lowercase
- `currency` stored uppercase
- `is_planned` defaults False; only True if explicitly marked
- `is_internal_transfer` defaults False; only True if explicit transfer keyword

---

## Tests

### `test_parser.py` — pure unit, no mocks

- RUB default when no currency token
- Inline USD overrides default
- `+` prefix → direction=income
- Income keyword `зп` → direction=income
- `перевод` → direction=expense, is_internal_transfer=True
- `вчера` date hint resolves correctly
- `DD.MM` date parsing
- Missing amount → parse_status=needs_correction, row not dropped
- `[planned]` suffix → is_planned=True
- Multiple lines split on `/`

### `test_normalizer.py` — unit, mock tag fetch

- Fingerprint format matches spec exactly
- Known tag exact match sets primary_tag
- No match → primary_tag=None
- occurred_at formatted as +03:00

### `test_mass_add.py` — integration, respx mocks httpx

- Full flow: raw text → POST body contains source="openclaw" on every row
- Duplicate fingerprint match → row skipped in POST
- `--force-duplicates` → duplicate row included in POST
- `needs_correction` rows included in POST (not dropped)
- `--confirm` flag skips interactive prompt
- Post-insert summary counts match

---

## Out of Scope

- Mass edit / PATCH
- Cashflow sheet generation
- Account attribution (`account_id` = null)
- Balance snapshot writes
- Telegram bot integration
- Google Sheets

---

## Acceptance Criteria

1. 10 messy mixed lines → clean preview → confirm → exactly those rows in DB
2. Duplicate fingerprint rows flagged in preview, skipped on insert by default
3. Uncertain rows land with `parse_status="needs_correction"`, not dropped
4. Every inserted row has `source="openclaw"` (verified by SELECT after insert in tests)
5. README in hastlefam updated with `openclaw mass-add` usage
