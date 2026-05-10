# OpenClaw Hardening — Operational Contract Design

**Date:** 2026-05-10  
**Scope:** Documentation-only. No code, no migrations, no schema changes.  
**Files changed:** `docs/openclaw-agent-instructions.md`, `CLAUDE.md`

---

## Goal

Harden `openclaw-agent-instructions.md` from a capability guide into a strict operational contract. OpenClaw is already live and writing directly to production Supabase via service role key — the rules it operates under must be unambiguous before any new capabilities are added.

---

## Context

OpenClaw is an external AI agent wired to the Telegram bot via Whisper STT. It bypasses FastAPI entirely and speaks Supabase REST directly using `SUPABASE_SERVICE_ROLE_KEY`. This is intentional MVP/agent mode, not a gap.

All columns required by the new rules (`source`, `parse_status`, `dedup_fingerprint`, `is_planned`, `is_internal_transfer`) are already live in production — confirmed via ORM models and migrations 0004–0020. No migration prerequisite exists.

---

## Document Structure (new order)

```
## Contract & Prohibitions     ← leads the doc; OpenClaw reads rules before capabilities
## Connection                  ← unchanged
## Schema Reference            ← extended with missing fields and corrected direction enum
## Tool 1: Mass-Add (Voice)    ← rewritten flow with full preview gate before POST
## Tool 2: Finance Advisor     ← updated with mandatory invariant filters
## Error Handling              ← extended
## Quick-Reference Headers     ← unchanged
```

---

## Section Design

### Contract & Prohibitions

Leads the document. Hard rules before any how-to content.

**Permitted:**
- Read and aggregate finance data (read-only queries, no side effects)
- Bulk-create transactions after full preview + explicit user confirmation
- Single-row PATCH with explicit per-row user confirmation only

**Hard prohibited — no exceptions:**
- DELETE any row from any table
- ALTER, DROP, or CREATE tables, enums, schemas, or indexes
- Run or suggest migrations
- Bulk PATCH without explicit per-batch user confirmation

**Required fields on every INSERT into `transactions`:**
- `household_id`
- `direction`
- `amount`
- `currency`
- `occurred_at`
- `source = "openclaw"` (always, no exceptions)
- `parse_status` — uncertain items use `"needs_correction"`, never silently omitted
- `dedup_fingerprint` — include wherever constructable (SHA-256 of `household_id|date|amount|currency|merchant|direction|telegram`)

**Financial invariants (ЗАКОН) — apply to every query:**
- `is_planned=true` → never actual spend/income; always filter out
- `is_internal_transfer=true` → never spend/income; always filter out
- `direction=exchange` → excluded from all spend/income totals; always filter out
- Every spend/income query must explicitly filter all three

---

### Schema Reference — changes

**`direction` enum correction:** current doc says `expense | income | transfer`. Correct values are `expense | income | transfer | exchange`. Add `exchange` with a note that it is excluded from spend/income analysis.

**New columns added to `transactions` table reference:**

| Column | Type | Notes |
|---|---|---|
| `source` | string(64) | Always `"openclaw"` for OpenClaw inserts. DB default is `"manual"`. |
| `parse_status` | string(32) | `"ok"` = confident parse; `"needs_correction"` = uncertain; nullable. |
| `dedup_fingerprint` | string(128) | SHA-256 of `household_id\|date\|amount\|currency\|merchant\|direction\|telegram`; nullable but include where possible. |
| `is_planned` | bool | Never set `true` for real transactions. DB default `false`. |
| `is_internal_transfer` | bool | Set `true` only for explicit intra-household fund movements. DB default `false`. |

---

### Tool 1: Mass-Add (Voice) — rewritten flow

**Step 1** — Resolve `household_id`  
**Step 2** — Resolve accounts + categories  
**Step 3** — Parse transcription into items. For each item determine direction, amount, currency, category, date, description. Uncertain items get `parse_status = "needs_correction"` — never silently drop them.  
**Step 4** — Show full preview of ALL items, including `needs_correction` ones (visually flagged). Show: direction, amount, currency, category, date for each. Show net total.  
**Step 5** — Ask for explicit confirmation before any write. Wait for yes.  
**Step 6** — Only after confirmation: bulk POST all items with required fields including `source = "openclaw"`.  
**Step 7** — Report inserted count and summary.

The confirmation gate is at step 5, after the user sees the full preview. `needs_correction` items are shown in the preview so the user can decide whether to proceed or correct first — OpenClaw does not make that decision.

---

### Tool 2: Finance Advisor — updates

**Mandatory query filters** (apply even when the user's question doesn't mention them):
```
&is_planned=eq.false
&is_internal_transfer=eq.false
```
Plus exclude `direction=eq.exchange` from any spend/income totals.

**Uncertainty disclosure** — if data is incomplete (zero rows returned, pagination truncated, category unresolvable), say so explicitly in the answer. Never interpolate or invent a number.

Existing response format unchanged: direct answer → brief context → one observation.

---

### CLAUDE.md OpenClaw section — changes

1. Label the mode explicitly: *"OpenClaw direct mode is MVP/agent mode — FastAPI is intentionally bypassed in this path."*
2. Add data flow note: Telegram voice → Whisper STT → OpenClaw → Supabase REST (no FastAPI).
3. Add `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` to the env vars table (currently missing entirely).

---

## Out of Scope

- No code changes
- No migrations
- No Google Sheets integration
- No FastAPI command gateway
- No CRM integration
- No frontend

---

## Success Criteria

- `docs/openclaw-agent-instructions.md` leads with contract rules before any capability description
- Every required field for inserts is documented
- Financial invariants are explicit and mandatory in both write and read flows
- Full preview gate is documented before bulk POST
- `CLAUDE.md` correctly describes OpenClaw as MVP/agent mode with env vars listed
