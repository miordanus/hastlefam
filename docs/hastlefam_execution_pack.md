# HastleFam — Claude Execution Pack v1

Status: implementation brief.
Audience: Claude as builder.
Goal: evolve the current raw Telegram bot into the approved money-copilot interaction model without product drift.

---

## 1. Product intent

You are NOT extending a generic family OS.
You are improving a Telegram-first money copilot for two.

Priority outcomes:
1. low-friction free-text capture;
2. immediate correction via inline actions;
3. useful monthly review;
4. planned payments awareness;
5. daily status habit loop;
6. trustworthy multi-currency support.

Do not optimize for “smartness”.
Optimize for trust, clarity, and working vertical slices.

---

## 2. Current-state conflicts you must actively override

The existing repository / docs may still reflect older behavior such as:
- recurring-first upcoming logic;
- default USD assumptions;
- silent duplicate skip;
- “no menus, no forms” framing;
- technical troubleshooting language exposed to users.

Treat those as legacy unless explicitly reconfirmed.

---

## 3. Approved interaction contract

### Input model
- free text is the default path;
- commands remain as fallback utilities;
- `/add` may stay for now but is not the main UX;
- category can be supplied inline via `#category` syntax.

### After capture
The bot should show a confirmation plus inline actions.
Only show the actions that are still relevant.

Core inline actions:
- date
- category
- planned payment
- currency / rate
- edit
- done

### Error handling
- never silently discard input;
- never silently skip likely duplicates;
- if duplicate suspicion is high, ask for confirmation;
- if key data is missing, ask for it directly;
- if category is missing, save the record if possible and immediately nudge to complete category.

### Planned payments
- planned payments are a first-class user-facing concept in this release;
- do not center the UX around recurring payments;
- `/upcoming` should support a planned-payments view;
- `/month` must show what is planned for the rest of the current month.

### Daily status
- one push per day at 10:00 MSK;
- short, useful, not spammy;
- must include month progress, nearby planned payments, and missing-data attention where relevant.

### Multi-currency
Supported in MVP:
- RUB
- USD
- USDT
- EUR

Exchange flow:
- user can record conversion manually;
- rate can be computed from entered amounts if not explicitly typed;
- conversion must not be double-counted as income.

---

## 4. Scope for the next implementation wave

### Must implement
1. free text default capture;
2. keep commands as fallback;
3. post-capture inline actions;
4. new user-facing copy based on approved copy pack;
5. duplicate confirm flow instead of silent skip;
6. category completion prompt;
7. `/month` redesign around readable monthly status;
8. planned payments for month awareness;
9. daily status update at 10:00 MSK;
10. multi-currency support for RUB / USD / USDT / EUR;
11. manual exchange flow with derived-rate support.

### Can defer
- advanced recurring engine;
- web-first UX;
- LLM-first categorization or parsing;
- finance forecasting;
- family/task scope expansion.

---

## 5. What NOT to do

- do not rewrite the whole app;
- do not introduce broad abstractions first;
- do not move product logic into LLM;
- do not keep legacy silent dedup behavior;
- do not keep default USD as the invisible fallback worldview;
- do not use recurring jargon in end-user screens where planned payments are the intended concept;
- do not invent new product copy outside the approved copy pack unless necessary.

---

## 6. UX rules

### Free text grammar
Support at least these patterns:
- `{amount} {merchant}`
- `{amount} {merchant} {currency}`
- `{amount} {merchant} #{category}`
- `{amount} {merchant} {currency} #{category}`

Handle decimal comma and decimal dot.

### Post-capture behavior
After a successful save:
- send short confirmation;
- render only relevant inline actions;
- if category missing, prompt for it immediately.

### Partial parse behavior
If amount exists but one or more secondary fields are missing:
- save if core capture is still trustworthy;
- ask for missing field(s) via guided interaction.

### Duplicate behavior
Preferred detection principle:
- only treat records as likely duplicates under strong similarity;
- if there is text difference, bias toward saving;
- if duplicate suspicion is still high, ask user to confirm.

No silent drop.

### Monthly review behavior
`/month` must be human-readable.
Target structure:
- spend block;
- income block;
- planned till month end;
- top categories;
- attention block.

No duplicate headings.
No raw technical labels.

### Upcoming behavior
`/upcoming` should show upcoming planned payments.
Keep it useful and short.

### Exchange behavior
The exchange flow should be a guided operation.
It must store conversion details in a way that does not create fake income.

---

## 7. Copy implementation rules

Use the approved copy from `02_hastlefam_copy_pack.md`.

Hard rules:
- Russian language for user-facing screens;
- moderate emoji only;
- calm and useful tone;
- no technical internal vocabulary;
- no hype;
- no playful mascot voice.

If implementation needs one extra message not covered by the pack:
- keep it short;
- match the same style;
- prefer operational clarity over flair.

---

## 8. Suggested delivery order

### Block A — input and correction
- free text parser updates;
- `#category` support;
- post-capture inline actions;
- missing category/date/currency prompts;
- duplicate confirm flow.

### Block B — reporting and planning
- `/month` redesign;
- `/upcoming` planned-payments output;
- planned-payment creation/edit flow.

### Block C — multi-currency and daily loop
- currency enum expansion where needed;
- exchange flow and storage;
- derived-rate behavior;
- 10:00 MSK daily status update job.

Do not merge all logic into one giant unreviewable blob if avoidable.
Use small but vertical slices.

---

## 9. Acceptance criteria

### Capture
- user can record with free text without using commands;
- command fallback still works;
- category can be passed via `#category`.

### Correction
- user can change date/category/currency from inline actions;
- bot shows only relevant actions after capture;
- missing category is surfaced immediately.

### Duplicate
- same-ish records are not silently discarded;
- user gets confirm choice before suppression.

### Month summary
- output is readable in one screen on Telegram;
- no duplicate month labels;
- includes planned rest-of-month block.

### Daily status
- status update can be generated in the approved structure;
- schedule target is 10:00 MSK.

### Multi-currency
- user can record RUB, USD, USDT, EUR;
- exchange does not double-count as income;
- summary can show per-currency blocks and optional converted base block.

---

## 10. Tests Claude should add or update

Minimum test coverage to add/update:
- free text parser with `#category`;
- partial parse leading to clarification flow;
- duplicate confirm path;
- record save when text differs but amount matches;
- planned payment rendering in `/upcoming`;
- `/month` rendering shape;
- exchange conversion not counted as income;
- multi-currency summaries with missing-rate attention.

---

## 11. Implementation notes

- keep deterministic logic first;
- avoid hidden side effects in capture flows;
- reuse existing finance/review primitives if they help, but do not let legacy naming force the wrong UX;
- if schema changes are needed, make them explicit;
- keep operator burden low.

---

## 12. Definition of success

Success is not “more features”.
Success is:
- user can log money naturally;
- user can correct it immediately;
- month summary is readable;
- planned payments are visible;
- daily status is useful;
- multi-currency data is honest.
