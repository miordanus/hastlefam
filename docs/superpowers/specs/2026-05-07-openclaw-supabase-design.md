# Design: Openclaw Agent ↔ Supabase Interface

**Date:** 2026-05-07  
**Status:** Approved

## Problem
Openclaw (external AI agent, already live with Whisper STT) needs an interface to read and write the hastlefam Supabase database for two use cases:
1. Mass-add transactions from voice transcriptions
2. Answer finance questions as an AI advisor

## Approach
No new code. Deliver a markdown instructions document that openclaw loads as its system-prompt context. Openclaw uses the Supabase REST API directly with the service role key.

## Deliverable
`docs/openclaw-agent-instructions.md` — covers:
- Connection setup (URL, headers, schema profile)
- Schema reference for all relevant tables
- Step-by-step tool patterns for mass-add and advisor flows
- Enum values, seeded category names, ambiguity rules, error handling

## Out of scope
- New FastAPI endpoints (not needed for this phase)
- Telegram bot changes (bot already wired to openclaw)
- New DB migrations (schema is complete)
