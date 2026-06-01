-- One-time, opt-in data cleanup — RUN MANUALLY, NOT part of `alembic upgrade`.
--
-- Background: the /balances reconcile flow used to mint a fixed
-- «корректировка» transaction equal to (new snapshot − previous snapshot).
-- That number never updated, so a past-dated expense added later did not
-- reduce it. Reconciliation drift is now derived on the fly in the data-health
-- view (FinanceService.data_health / _account_drift) from the snapshot window
-- and attributed transactions.
--
-- These legacy rows would now be DOUBLE-COUNTED (once as the stored delta, once
-- as the derived drift). Delete them after deploying the new code. Idempotent:
-- safe to re-run; matches only the auto-generated reconciliation deltas, not
-- anything a user tagged «корректировка» by hand.
--
-- Review the SELECT first, then run the DELETE.

-- Preview what will be removed:
-- SELECT id, account_id, amount, occurred_at, merchant_raw, source, parse_status
-- FROM hastlefam.transactions
-- WHERE primary_tag = 'корректировка'
--   AND source = 'telegram'
--   AND merchant_raw LIKE 'Корректировка:%';

BEGIN;

DELETE FROM hastlefam.transactions
WHERE primary_tag = 'корректировка'
  AND source = 'telegram'
  AND merchant_raw LIKE 'Корректировка:%';

COMMIT;
