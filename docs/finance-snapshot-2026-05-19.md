# Cashflow analysis — 2026-05-19 → 2026-07-31

Analyst pass. The DB has 354 actual transactions and good historical depth, but balances, recurring items, and forward-looking planned items are too thin to compute a credible end-of-July position without input. This document inventories what exists, what's missing, and a best-guess forecast scaffold pending user confirmation.

## 1. Accounts and balances

Last snapshot date: **2026-04-01** for all 6 accounts (7 weeks stale).

| Account | Ccy | Apr-1 | Implied today (rollforward) | Confidence | Notes |
|---|---|---:|---:|---|---|
| Cash | RUB | 95,000 | **9,102** | Medium-high | 27 actual expense tx since Apr 1. No income, no FX in. |
| T-molly | USD | 3,000 | 3,000 | Low | Zero tx booked here, but household uses USD. Probably untouched savings or a placeholder. |
| tm | RUB | 0 | −37,000 | Low | 1 tx; account purpose unclear. |
| tmcc (credit) | RUB | −186,480 | −186,480 | Low | Zero tx booked, but legacy planned shows 80–106K RUB/mo payments. Balance has certainly drifted. |
| USDT | USDT | 15 | 3,496 | Medium-low | Implied via 3 income tx but ignores the 5,000 USDT in outgoing exchanges (Apr+May). Net should be lower. |
| Наличные | RUB | — never | — | — | Never snapshotted. Likely a duplicate of `Cash`; consider deactivating. |

Rollforward limitations: 15 of 90 recent transactions have NULL `account_id` (17%), 5 currency exchanges and 15 internal transfers move money between accounts without standard income/expense rows. Per-account math is incomplete.

## 2. Recurring structure (reconstructed)

`recurring_payments` table is empty. The 15 legacy `planned_payments` rows (all status='pending', all past — but matching exactly with `transactions(is_planned=true)` rows for Apr+May, confirming unification) reveal the actual recurring pattern:

| Item | Amount | Ccy | Cadence | Tag |
|---|---:|---|---|---|
| Ипотека (mortgage) | 37,000 | RUB | monthly, ~18th | housing |
| Счета ЖКХ (utilities) | 10,000 | RUB | monthly, ~18th | housing |
| tmcc payment | 80,200 → 106,280 | RUB | monthly, ~10th (varies with usage) | debt_repayment |
| ИП Армения — бухгалтер | 25,000 | AMD (~5,000 RUB) | monthly, ~10th | gov |
| ИП Армения — налог | ~130,000 | AMD (~26,000 RUB) | monthly, ~20th | gov |
| RevOps freelance income | ~3,000–4,200 | USDT (~220–310K RUB) | monthly | income |

Also visible in actuals but not yet captured as recurring:
- Food/groceries ~80,000 RUB/mo (from actual tx aggregates Jan–May 2026)
- Other discretionary ~50,000–100,000 RUB/mo

## 3. Baselines (actual, Jan–May 2026 RUB expense, filtered)

| Month | RUB expense | Tx count |
|---|---:|---:|
| Dec 2025 | 71,437 | 54 |
| Jan 2026 | 339,688 | 71 |
| Feb 2026 | 227,693 | 44 |
| Mar 2026 | 191,648 | 59 |
| Apr 2026 | 116,180 | 17 |
| May MTD | 62,272 | 53 |

**Three-month avg (Feb–Apr): 178K RUB/mo actual.** Excluding Jan as outlier and Apr as plausibly under-tracked, run-rate is ~200K RUB/mo of *discretionary + uncategorized* spend, on top of the recurring items above.

## 4. USDT → RUB conversion pattern

| Date | USDT out | RUB in | Status |
|---|---:|---:|---|
| 2025-12-31 | 6,500 | 507,000 | actual |
| 2026-03-13 | 3,000 | 232,500 | actual |
| 2026-04-15 | 3,500 | 257,250 | actual |
| 2026-05-08 | 1,500 | 109,000 | actual |
| **2026-06-12** | **3,500** | **255,500** | **planned** |

Conversion cadence is ~monthly. June already planned. July conversion not yet planned — likely 3,000–3,500 USDT.

## 5. Forward-looking planned items already in DB

`transactions(is_planned=true)` between today and 2026-07-31:
- May rump: 3 RUB expenses totaling 153,280
- June: 1 planned exchange (3,500 USDT → 255,500 RUB)
- **July: nothing**

## 6. Best-guess forecast (assumptions clearly flagged)

**Starting position (Apr-1 + rollforward), in RUB equivalent at 73.13 RUB/USD/USDT, 0.1986 RUB/AMD:**

| Account | Local | RUB equiv |
|---|---:|---:|
| Cash | 9,102 RUB | 9,102 |
| tm | −37,000 RUB | −37,000 |
| tmcc | −186,480 RUB | −186,480 |
| T-molly | 3,000 USD | 219,390 |
| USDT | ~2,000 USDT (adjusted) | 146,260 |
| **Total liquid net** | | **~151,300 RUB** |

(T-molly's 219K is dubious — see ask #1 below.)

**Monthly run-rate (RUB equivalent):**

| Inflow | Amount/mo |
|---|---:|
| USDT freelance income | +220,000 |
| **Total in** | **+220,000** |

| Outflow | Amount/mo |
|---|---:|
| Mortgage | 37,000 |
| Utilities | 10,000 |
| tmcc payment | ~93,000 |
| AMD accountant | ~5,000 |
| AMD taxes | ~26,000 |
| Discretionary actuals | ~178,000 |
| **Total out** | **~349,000** |

**Net: ~−129,000 RUB/month** (running on credit/savings reserve).

**Forecast for 2026-05-19 → 2026-07-31 (~2.4 months):**

- Net burn: ~310,000 RUB over the window.
- Projected liquid net at 2026-07-31: ~**−160,000 RUB** (deteriorating; credit card balance grows, USD/USDT reserves draw down).
- This is a deficit story. Either income is undercounted (likely — USDT income flow vs USDT exchange flow are not perfectly aligned in the data) or spending is running ahead of income.

## 7. What's needed from the user to tighten this

These are the gaps that turn the analyst's best-guess into an actual forecast:

**Critical (blocks the whole forecast):**
1. **Today's balance per account.** At minimum: Cash, tmcc (credit), T-molly (USD), USDT, and confirm `tm` and `Наличные` are real or should be deactivated.
2. **Monthly USDT income — is it consistent?** Apr planned 4,200; actuals were 2,000 (Nov), 3,072 (Dec), 2,443 (Feb), 3,481 (May). What's the expected June and July figure?
3. **tmcc payment policy** — fixed amount? % of balance? Will it be ~100K RUB in June and July?

**Important (changes forecast materially):**
4. Any **one-off items** through end of July: travel, large purchases, expected refunds, expected income outside USDT freelance, planned currency exchange (it looks like one happens monthly — should we book July's now?).
5. Is **AMD tax** monthly or quarterly? April had 3 AMD-tax rows totaling 269K AMD — was that arrears clearing or a quarterly cycle?
6. What discretionary categories should be modeled forward (food has clear ~80K/mo pattern; other categories vary)?

**Nice to have:**
7. Confirm the `tm` and `Наличные` accounts are not in use; deactivate if so.
8. Decide: should I populate `recurring_payments` rows for the 5 confirmed items above so future forecasts auto-build?

## 8. Suggested next steps (in order)

1. User provides today's balances for 3–5 critical accounts → I insert `balance_snapshots`.
2. User confirms recurring inventory (items 2–6 above) → I populate `recurring_payments` and materialize June+July `transactions(is_planned=true)` for each occurrence.
3. Re-run `cashflow_projection(household_id, days=74)` against the now-clean data → produce the final number.

Until step 1 is done, treat the forecast in §6 as directional only.
