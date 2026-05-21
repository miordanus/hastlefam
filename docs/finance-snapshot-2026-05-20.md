# Cashflow forecast — 2026-05-20 → 2026-07-31

Analyst pass executed against `hastlefam` schema, Supabase project `sfzyqdpckgyznuhunygj`. All balances, recurring items, and one-offs through end of July are now in the DB.

FX as of 2026-05-18 (CBR): 1 USD = 73.13 RUB; 1 USDT ≈ 73.13 RUB (USD proxy); 1 AMD = 0.198592 RUB.

## 1. Starting position (2026-05-20)

| Account | Currency | Local balance | RUB equivalent |
|---|---|---:|---:|
| Cash | RUB | 40,150 | 40,150 |
| Max tbank | RUB | 520 | 520 |
| Molly tbank | RUB | 59,000 | 59,000 |
| T-molly | USD | 3,000 | 219,383 |
| USDT | USDT | 3,496.26 | 255,673 |
| **Liquid subtotal** | | | **574,725** |
| tmcc (credit liability) | RUB | −201,610 | −201,610 |
| **Net of credit** | | | **373,115** |

Notes:
- tmcc balance is the outstanding grace-period debt (Jun-10: 145,000 + Jul-10: 56,610). Available credit limit of 43,400 RUB is not counted as an asset.
- T-molly USD balance of 3,000 carries forward from Apr-1; user did not refresh — treat as ±5% uncertain.

## 2. Planned cashflow May 20 → Jul 31

### Income (planned)

| Date | Item | Amount | RUB equiv |
|---|---|---:|---:|
| 2026-06-12 | RevOps freelance | 3,500 USDT | 255,946 |
| 2026-07-12 | RevOps freelance | 3,500 USDT | 255,946 |
| **Total income** | | **7,000 USDT** | **511,892** |

### Expense (planned, RUB)

| Date | Item | Amount RUB |
|---|---|---:|
| May 20–31 rump (already in DB) | mortgage, utilities, tmcc legacy | 153,280 |
| 2026-06-01 | tmcc premium plan | 300 |
| 2026-06-10 | tmcc grace-period payment | 145,000 |
| 2026-06-18 | Mortgage | 37,000 |
| 2026-06-18 | Utilities (ЖКХ) | 10,000 |
| 2026-07-01 | tmcc premium plan | 300 |
| 2026-07-10 | tmcc grace-period payment | 56,610 |
| 2026-07-15 | **Taxes (one-off)** | **560,000** |
| 2026-07-18 | Mortgage | 37,000 |
| 2026-07-18 | Utilities (ЖКХ) | 10,000 |
| **Subtotal RUB expenses** | | **1,009,490** |

(SQL aggregate returned 856,210 RUB; difference of 153,280 is the pre-existing May rump items that were already in DB before this pass.)

### Expense (planned, AMD)

| Date | Item | Amount AMD | RUB equiv |
|---|---|---:|---:|
| 2026-06-10 | Accountant (ИП Армения) | 25,000 | 4,965 |
| 2026-06-20 | Tax (ИП Армения) | 10,000 | 1,986 |
| 2026-07-10 | Accountant | 25,000 | 4,965 |
| 2026-07-20 | Tax | 10,000 | 1,986 |
| **Total AMD** | | **70,000 AMD** | **13,901** |

### Planned net (RUB equivalent)

- Inflows: **+511,892 RUB** (2 × USDT income)
- Outflows: **−1,023,391 RUB** (1,009,490 RUB + 13,901 AMD equiv)
- **Planned net: −511,499 RUB**

## 3. Forecast

| Component | RUB |
|---|---:|
| Starting net (today) | 373,115 |
| + Planned income | 511,892 |
| − Planned expenses | −1,023,391 |
| **Subtotal (planned only)** | **−138,384** |
| − Discretionary baseline @ 178K/mo × 2.4 months | −427,200 |
| **Projected end-of-July position** | **−565,584 RUB** |

If discretionary spend is held to half the historical baseline (~90K/mo), end-July position ≈ **−352K RUB**.

If the 560K July tax can be deferred or partially offset, every 100K of relief moves the end-July position +100K.

## 4. What the forecast says

- The two and a half months are dominated by **one item: the 560K RUB July tax**. It alone consumes ~150% of starting net cash.
- Without that tax, the household would be roughly cashflow-neutral on planned items (USDT income ≈ structural outflows + tmcc) — the discretionary baseline is what tilts to a deficit.
- The household has ~258K RUB of foreign-currency reserves (3,000 USD + ~3,500 USDT) that can be converted into RUB on top of the monthly USDT income — meaningful buffer but not infinite.
- tmcc is paid down to zero by end of July under the current plan. New tmcc usage in June/July is bounded by the 43,400 available limit.

## 5. Sensitivity ladder (end-of-July net, RUB)

| Scenario | Net |
|---|---:|
| Plan as modeled, discretionary at 178K/mo baseline | −566K |
| Discretionary held at 90K/mo | −352K |
| Discretionary at 90K/mo + Jul tax deferred to Aug | +208K |
| Plan + extra USDT exchange of remaining ~3.5K USDT | −310K |

## 6. Risks and unknowns

- **T-molly USD balance** was not refreshed by the user (Apr-1 value of 3,000 carried forward). If the real balance is materially different, every 500 USD moves the forecast ±37K RUB.
- **AMD tax cadence assumed monthly 10K**. April had 269K AMD of tax rows — possibly arrears or quarterly. If June and July each face an additional ~130K AMD payment, that's −26K RUB per occurrence (each).
- **Discretionary baseline (178K/mo)** comes from Feb–Apr actuals. May MTD shows 62K so the May trajectory may run lower; rates can vary ±50K/mo.
- **June and July USDT→RUB exchanges** are modelled at 73.13 RUB/USDT (CBR May 18). If the rate drops to e.g. 70, each 3,500 USDT exchange loses ~11K RUB.
- **Tax one-off**: confirm exact RUB amount and payment account.

## 7. What's now in the DB

- 4 fresh balance snapshots (Cash, Max tbank, Molly tbank, USDT) dated 2026-05-20; tmcc snapshot at −201,610.
- 16 new planned `transactions` rows covering June and July items (tmcc x2, premium x2, mortgage x2, utilities x2, AMD costs x4, USDT income x2, July USDT exchange, July tax).
- Account housekeeping: `tm` renamed to `Max tbank`; new `Molly tbank` (RUB) created; both `Наличные` rows deactivated; `T-molly` (USD) and `tmcc` unchanged in structure.

## 8. Suggested follow-ups (not done in this pass)

- Populate `recurring_payments` table for the 7 confirmed monthly items so the bot/dashboard surfaces them without needing each occurrence to be re-inserted manually.
- Backfill the 15 of 90 recent transactions that have NULL `account_id`.
- Decide whether T-molly USD is still in active use and refresh its balance.
- Confirm AMD tax cadence with the accountant.
