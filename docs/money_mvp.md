# Money-first MVP slice

## Architecture slice
- **Data**: `transactions`, `finance_categories`, `accounts`, `recurring_payments`, `owners`, `raw_import_transactions`.
- **Ingestion**: SQL import endpoint -> raw table -> normalization service -> transaction table.
- **Telegram**: default capture parser + `/month` + `/upcoming`.
- **Correction**: utilitarian HTML table for fast category fix / recurring linking.
- **Reminders**: daily recurring due scan with anti-duplicate event log checks.

## Safe autofill rules
- `currency`: default currency if absent.
- `source`: always set from import payload.
- `owner_id`/`account_id`: only from explicit source mapping.
- `category_id`: left null by default (correction flow first).
- `occurred_at`: fallback to now only with `parse_status=needs_correction`.
- `direction`: expense by default only for known expense source import.

## Telegram flows
- Send plain message: `149 spotify` -> rule-based parse -> transaction save.
- Low confidence -> bot asks to retry format and does not save silently.
- `/month` -> MTD totals + top categories + upcoming till month-end.
- `/upcoming` -> next 7 days recurring obligations.

## Manual review checklist
1. Import mixed SQL rows (missing date/merchant/category).
2. Confirm rows appear in raw table and normalized transactions.
3. Open correction screen and categorize uncategorized rows.
4. Add expense via plain Telegram text.
5. Run `/month` and verify calendar-MTD numbers.
6. Run `/upcoming` and verify next due recurring entries.
7. Run reminder job twice and verify second run skips duplicates.
