# LLM Prompt Contracts (MVP)

## Rules
- JSON output only.
- Validate against strict Pydantic schema.
- No invented dates, amounts, owners, statuses.
- LLM output saved as `llm_drafts` only.

## Contracts
1. parse: free text -> structured draft items.
2. meeting_summary: notes -> summary/decisions/task drafts.
3. finance_insight: transactions -> insight summary.
4. weekly_digest: sprint+finance summaries -> digest draft.

On failure: mark `validation_status=invalid`, save error text, emit `event_log` record.
