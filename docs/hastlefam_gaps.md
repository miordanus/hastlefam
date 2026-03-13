# HastleFam — Birds-Eye View / Gaps Before Final Prompt

Purpose: list the still-open product edges so old logic does not leak into implementation.
Status: not blockers for copy pack creation, but must be resolved in the next step-back interview.

---

## 1. Biggest product shift already approved

Old center of gravity:
- recurring payments;
- default USD;
- silent dedup;
- command-ish bot logic.

New center of gravity:
- free-text default capture;
- inline correction;
- planned payments;
- daily status loop;
- multi-currency household reality.

This is not a minor polish pass.
This is a product-contract change.

---

## 2. Open decision areas

### A. Income capture
Still needs explicit confirmation:
- should income use the same free-text grammar as expenses;
- should there be a symbol or keyword for income;
- how should exchange-related income-looking events be prevented from polluting income totals.

### B. Planned payment ownership
Still needs confirmation:
- owner choices;
- whether owner is mandatory in every planned payment;
- how owner appears in summaries.

### C. Base-currency summary
Approved direction:
- per-currency blocks plus optional converted base block.

Still open:
- what is the base currency by default;
- whether base currency is household-wide or user-specific;
- how stale manual rates are handled in monthly views.

### D. Category model
Approved direction:
- category can be parsed as `#category`.

Still open:
- canonical category naming format;
- whether user-facing categories are slug-like or human-readable labels;
- how aliases map to stored categories.

### E. Planned payment vs actual transaction link
Still open:
- does a planned payment become an actual transaction by confirmation;
- does payment creation clone fields or convert the same object;
- how to avoid double counting planned and actual in summaries.

### F. Daily status opt-out / tuning
Approved direction:
- one push daily at 10:00 MSK.

Still open:
- whether this is global default or per-user setting;
- whether weekends behave the same;
- whether empty/noise days should still push.

### G. `/upcoming` split
Approved direction:
- both nearby view and month context matter.

Still open:
- exact command design if both views stay;
- whether `/upcoming` is strictly next 7 days and `/month` contains the month horizon;
- whether a future `/planned` command is needed.

---

## 3. Hidden implementation risks

### Risk 1 — legacy model names will distort UX
If the codebase still uses `RecurringPayment` or similar as the most obvious primitive, implementation may wrongly drag user copy and user logic back to recurring-first.

### Risk 2 — multi-currency without explicit summary rules will create fake clarity
If converted totals are shown without transparent rate handling, trust will break.

### Risk 3 — duplicate logic can regress silently
If existing dedup behavior remains partially active, users may still lose entries without a clear prompt.

### Risk 4 — exchange may leak into income
If the exchange operation reuses standard transaction logic poorly, reports can become dishonest.

### Risk 5 — too many inline buttons can make Telegram feel heavy
Need to show only relevant actions, not the full control panel every time.

---

## 4. What is probably still missing from the product view

These are the most likely forgotten areas:
- explicit income input rules;
- exact owner behavior in shared household flows;
- category taxonomy and aliases;
- how planned payments are marked as done;
- what counts as “needs attention” severity in daily status;
- whether manual exchange can be edited later without corrupting summaries.

---

## 5. Recommended next-step interview focus

In the step-back interview, resolve these in order:
1. income grammar and exchange handling;
2. planned payment lifecycle;
3. category taxonomy / aliasing;
4. base-currency logic;
5. daily status delivery edge cases;
6. command map (`/month`, `/upcoming`, maybe future `/planned`).

---

## 6. Bottom line

The current work is already enough to write copy and an execution brief.
But before the final master prompt, the product needs one more deliberate pass on the six open areas above.
Otherwise Claude may implement a technically valid but semantically wrong finance bot.
