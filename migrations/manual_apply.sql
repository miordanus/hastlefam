-- =============================================================================
-- HastleFam: Complete migration script (0001 → 0004)
-- Run this in the Supabase SQL Editor to apply all migrations.
-- Safe to re-run (uses IF NOT EXISTS / conditional checks throughout).
-- =============================================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0001: Initial Schema
-- ─────────────────────────────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS hastlefam;

-- Enum types
DO $$ BEGIN
    CREATE TYPE hastlefam.task_type_enum AS ENUM ('task', 'recurring_task', 'shopping_item');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE hastlefam.task_status_enum AS ENUM ('backlog', 'todo', 'in_progress', 'done', 'canceled');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE hastlefam.note_type_enum AS ENUM ('note', 'blocker', 'idea');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE hastlefam.meeting_type_enum AS ENUM ('sprint_planning', 'weekly_review', 'finance_review', 'household_sync');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE hastlefam.currency_enum AS ENUM ('RUB', 'USD', 'USDT', 'EUR', 'AMD');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE hastlefam.category_kind_enum AS ENUM ('expense', 'income');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE hastlefam.transaction_direction_enum AS ENUM ('expense', 'income', 'transfer');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE hastlefam.draft_type_enum AS ENUM ('parse', 'meeting_summary', 'finance_insight', 'weekly_digest');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Tables

CREATE TABLE IF NOT EXISTS hastlefam.households (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        varchar(255) NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.users (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES hastlefam.households(id),
    telegram_id  varchar(64) NOT NULL UNIQUE,
    name         varchar(255) NOT NULL,
    is_active    boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.areas (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES hastlefam.households(id),
    name         varchar(255) NOT NULL,
    is_default   boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.sprints (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES hastlefam.households(id),
    title        varchar(255) NOT NULL,
    start_date   date NOT NULL,
    end_date     date NOT NULL,
    status       varchar(32) NOT NULL DEFAULT 'planned',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.meetings (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES hastlefam.households(id),
    meeting_type hastlefam.meeting_type_enum NOT NULL,
    scheduled_at timestamptz NOT NULL,
    started_at   timestamptz,
    ended_at     timestamptz,
    status       varchar(32) NOT NULL DEFAULT 'scheduled',
    agenda_text  text,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.tasks (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id  uuid NOT NULL REFERENCES hastlefam.households(id),
    area_id       uuid REFERENCES hastlefam.areas(id),
    sprint_id     uuid REFERENCES hastlefam.sprints(id),
    owner_user_id uuid NOT NULL REFERENCES hastlefam.users(id),
    title         varchar(255) NOT NULL,
    description   text,
    task_type     hastlefam.task_type_enum NOT NULL DEFAULT 'task',
    status        hastlefam.task_status_enum NOT NULL DEFAULT 'backlog',
    priority      varchar(16) NOT NULL DEFAULT 'medium',
    due_date      timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_tasks_household_id ON hastlefam.tasks (household_id);
CREATE INDEX IF NOT EXISTS ix_tasks_owner_user_id ON hastlefam.tasks (owner_user_id);

CREATE TABLE IF NOT EXISTS hastlefam.decisions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES hastlefam.households(id),
    meeting_id   uuid REFERENCES hastlefam.meetings(id),
    title        varchar(255) NOT NULL,
    description  text,
    decided_at   timestamptz NOT NULL DEFAULT now(),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.notes (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id   uuid NOT NULL REFERENCES hastlefam.households(id),
    author_user_id uuid NOT NULL REFERENCES hastlefam.users(id),
    area_id        uuid REFERENCES hastlefam.areas(id),
    meeting_id     uuid REFERENCES hastlefam.meetings(id),
    note_type      hastlefam.note_type_enum NOT NULL DEFAULT 'note',
    content        text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.finance_categories (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid REFERENCES hastlefam.households(id),
    name         varchar(255) NOT NULL,
    kind         hastlefam.category_kind_enum NOT NULL,
    is_default   boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.accounts (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id  uuid NOT NULL REFERENCES hastlefam.households(id),
    owner_user_id uuid REFERENCES hastlefam.users(id),
    name          varchar(255) NOT NULL,
    currency      hastlefam.currency_enum NOT NULL,
    is_shared     boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.transactions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES hastlefam.households(id),
    account_id   uuid REFERENCES hastlefam.accounts(id),
    category_id  uuid REFERENCES hastlefam.finance_categories(id),
    user_id      uuid REFERENCES hastlefam.users(id),
    direction    hastlefam.transaction_direction_enum NOT NULL,
    amount       numeric(14,2) NOT NULL,
    currency     hastlefam.currency_enum NOT NULL,
    occurred_at  timestamptz NOT NULL,
    description  text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_transactions_household_occurred_at ON hastlefam.transactions (household_id, occurred_at);

CREATE TABLE IF NOT EXISTS hastlefam.recurring_payments (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id  uuid NOT NULL REFERENCES hastlefam.households(id),
    account_id    uuid REFERENCES hastlefam.accounts(id),
    category_id   uuid REFERENCES hastlefam.finance_categories(id),
    name          varchar(255) NOT NULL,
    amount        numeric(14,2) NOT NULL,
    currency      hastlefam.currency_enum NOT NULL,
    period        varchar(32) NOT NULL DEFAULT 'monthly',
    next_due_date date NOT NULL,
    is_active     boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.savings_goals (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id   uuid NOT NULL REFERENCES hastlefam.households(id),
    name           varchar(255) NOT NULL,
    target_amount  numeric(14,2) NOT NULL,
    currency       hastlefam.currency_enum NOT NULL,
    deadline       date,
    current_amount numeric(14,2) NOT NULL DEFAULT 0,
    status         varchar(32) NOT NULL DEFAULT 'active',
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.reminders (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES hastlefam.households(id),
    user_id      uuid NOT NULL REFERENCES hastlefam.users(id),
    entity_type  varchar(64) NOT NULL,
    entity_id    uuid NOT NULL,
    remind_at    timestamptz NOT NULL,
    status       varchar(32) NOT NULL DEFAULT 'pending',
    channel      varchar(32) NOT NULL DEFAULT 'telegram',
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.digests (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES hastlefam.households(id),
    digest_type  varchar(32) NOT NULL,
    period_start date NOT NULL,
    period_end   date NOT NULL,
    content_json json NOT NULL DEFAULT '{}',
    status       varchar(32) NOT NULL DEFAULT 'draft',
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.llm_drafts (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id      uuid NOT NULL REFERENCES hastlefam.households(id),
    draft_type        hastlefam.draft_type_enum NOT NULL,
    source_text       text NOT NULL,
    input_json        json NOT NULL DEFAULT '{}',
    output_json       json,
    validation_status varchar(32) NOT NULL DEFAULT 'pending',
    error_text        text,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hastlefam.event_log (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid REFERENCES hastlefam.households(id),
    user_id      uuid REFERENCES hastlefam.users(id),
    event_type   varchar(128) NOT NULL,
    entity_type  varchar(64),
    entity_id    uuid,
    payload      json NOT NULL DEFAULT '{}',
    severity     varchar(16) NOT NULL DEFAULT 'info',
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_event_log_created_event ON hastlefam.event_log (created_at, event_type);


-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0002: Seed Defaults
-- ─────────────────────────────────────────────────────────────────────────────

-- Create default household if none exists
INSERT INTO hastlefam.households (id, name, created_at, updated_at)
SELECT gen_random_uuid(), 'Default Household', now(), now()
WHERE NOT EXISTS (SELECT 1 FROM hastlefam.households LIMIT 1);

-- Seed default areas (skip if already seeded)
DO $$
DECLARE
    hid uuid;
    area_names text[] := ARRAY[
        'Finances', 'Home', 'Relationship', 'Health',
        'Admin', 'Purchases', 'Travel', 'Work / Side Projects'
    ];
    area_name text;
BEGIN
    SELECT id INTO hid FROM hastlefam.households ORDER BY created_at LIMIT 1;

    IF NOT EXISTS (SELECT 1 FROM hastlefam.areas WHERE household_id = hid AND is_default = true LIMIT 1) THEN
        FOREACH area_name IN ARRAY area_names LOOP
            INSERT INTO hastlefam.areas (id, household_id, name, is_default, created_at, updated_at)
            VALUES (gen_random_uuid(), hid, area_name, true, now(), now());
        END LOOP;
    END IF;
END $$;

-- Seed default expense categories (skip if already seeded)
DO $$
DECLARE
    hid uuid;
    expense_names text[] := ARRAY[
        'Housing', 'Utilities', 'Internet & Mobile', 'Groceries',
        'Eating Out / Delivery', 'Transport', 'Health / Medicine', 'Pets',
        'Household Goods', 'Subscriptions', 'Shopping / Personal', 'Travel',
        'Gifts', 'Education', 'Taxes / Fees', 'Debt / Loan Payments',
        'Savings / Investments', 'Other'
    ];
    cat_name text;
BEGIN
    SELECT id INTO hid FROM hastlefam.households ORDER BY created_at LIMIT 1;

    IF NOT EXISTS (SELECT 1 FROM hastlefam.finance_categories WHERE household_id = hid AND kind = 'expense' AND is_default = true LIMIT 1) THEN
        FOREACH cat_name IN ARRAY expense_names LOOP
            INSERT INTO hastlefam.finance_categories (id, household_id, name, kind, is_default, created_at)
            VALUES (gen_random_uuid(), hid, cat_name, 'expense', true, now());
        END LOOP;
    END IF;
END $$;

-- Seed default income categories (skip if already seeded)
DO $$
DECLARE
    hid uuid;
    income_names text[] := ARRAY[
        'Salary', 'Freelance / Consulting', 'Business Income', 'Transfers In',
        'Investment Income', 'Cashback / Refunds', 'Other'
    ];
    cat_name text;
BEGIN
    SELECT id INTO hid FROM hastlefam.households ORDER BY created_at LIMIT 1;

    IF NOT EXISTS (SELECT 1 FROM hastlefam.finance_categories WHERE household_id = hid AND kind = 'income' AND is_default = true LIMIT 1) THEN
        FOREACH cat_name IN ARRAY income_names LOOP
            INSERT INTO hastlefam.finance_categories (id, household_id, name, kind, is_default, created_at)
            VALUES (gen_random_uuid(), hid, cat_name, 'income', true, now());
        END LOOP;
    END IF;
END $$;


-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0003: Legacy Public-to-Hastlefam
-- Move any tables that exist in public schema into hastlefam schema.
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    tbl text;
    tables text[] := ARRAY[
        'households', 'users', 'areas', 'sprints', 'tasks',
        'decisions', 'notes', 'meetings', 'transactions',
        'finance_categories', 'accounts', 'recurring_payments',
        'savings_goals', 'reminders', 'digests', 'llm_drafts', 'event_log'
    ];
BEGIN
    FOREACH tbl IN ARRAY tables LOOP
        IF to_regclass('public.' || tbl) IS NOT NULL
           AND to_regclass('hastlefam.' || tbl) IS NULL THEN
            EXECUTE 'ALTER TABLE public.' || tbl || ' SET SCHEMA hastlefam';
        END IF;
    END LOOP;
END $$;


-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0004: Money MVP Slice
-- ─────────────────────────────────────────────────────────────────────────────

-- New table: owners
CREATE TABLE IF NOT EXISTS hastlefam.owners (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES hastlefam.households(id),
    name         varchar(255) NOT NULL,
    slug         varchar(32) NOT NULL,
    is_active    boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_owners_household_id ON hastlefam.owners (household_id);

-- New table: raw_import_transactions
CREATE TABLE IF NOT EXISTS hastlefam.raw_import_transactions (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id         uuid NOT NULL REFERENCES hastlefam.households(id),
    import_batch_id      varchar(128) NOT NULL,
    source_name          varchar(64) NOT NULL,
    imported_at          timestamptz NOT NULL DEFAULT now(),
    raw_payload          json NOT NULL DEFAULT '{}',
    raw_occurred_at      timestamptz,
    raw_amount           numeric(14,2),
    raw_currency         varchar(8),
    raw_merchant         varchar(255),
    raw_description      text,
    normalization_status varchar(32) NOT NULL DEFAULT 'pending',
    normalization_error  text
);
CREATE INDEX IF NOT EXISTS ix_raw_import_status_imported_at ON hastlefam.raw_import_transactions (normalization_status, imported_at);

-- Add new columns to accounts
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='accounts' AND column_name='owner_id') THEN
        ALTER TABLE hastlefam.accounts ADD COLUMN owner_id uuid REFERENCES hastlefam.owners(id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='accounts' AND column_name='is_active') THEN
        ALTER TABLE hastlefam.accounts ADD COLUMN is_active boolean NOT NULL DEFAULT true;
    END IF;
END $$;

-- Make account_id and category_id nullable on transactions
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='transactions' AND column_name='account_id') THEN
        ALTER TABLE hastlefam.transactions ALTER COLUMN account_id DROP NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='transactions' AND column_name='category_id') THEN
        ALTER TABLE hastlefam.transactions ALTER COLUMN category_id DROP NOT NULL;
    END IF;
END $$;

-- Add new columns to transactions
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='transactions' AND column_name='owner_id') THEN
        ALTER TABLE hastlefam.transactions ADD COLUMN owner_id uuid REFERENCES hastlefam.owners(id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='transactions' AND column_name='merchant_raw') THEN
        ALTER TABLE hastlefam.transactions ADD COLUMN merchant_raw varchar(255);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='transactions' AND column_name='description_raw') THEN
        ALTER TABLE hastlefam.transactions ADD COLUMN description_raw text;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='transactions' AND column_name='source') THEN
        ALTER TABLE hastlefam.transactions ADD COLUMN source varchar(64) NOT NULL DEFAULT 'manual';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='transactions' AND column_name='raw_import_id') THEN
        ALTER TABLE hastlefam.transactions ADD COLUMN raw_import_id uuid REFERENCES hastlefam.raw_import_transactions(id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='transactions' AND column_name='parse_status') THEN
        ALTER TABLE hastlefam.transactions ADD COLUMN parse_status varchar(32);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='transactions' AND column_name='parse_confidence') THEN
        ALTER TABLE hastlefam.transactions ADD COLUMN parse_confidence numeric(4,3);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='transactions' AND column_name='dedup_fingerprint') THEN
        ALTER TABLE hastlefam.transactions ADD COLUMN dedup_fingerprint varchar(128);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='transactions' AND column_name='updated_at') THEN
        ALTER TABLE hastlefam.transactions ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_transactions_dedup_fingerprint ON hastlefam.transactions (dedup_fingerprint);
CREATE INDEX IF NOT EXISTS ix_transactions_owner_id ON hastlefam.transactions (owner_id);

-- Add new columns to recurring_payments
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='recurring_payments' AND column_name='owner_id') THEN
        ALTER TABLE hastlefam.recurring_payments ADD COLUMN owner_id uuid REFERENCES hastlefam.owners(id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='recurring_payments' AND column_name='title') THEN
        ALTER TABLE hastlefam.recurring_payments ADD COLUMN title varchar(255);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='recurring_payments' AND column_name='amount_expected') THEN
        ALTER TABLE hastlefam.recurring_payments ADD COLUMN amount_expected numeric(14,2);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='recurring_payments' AND column_name='cadence') THEN
        ALTER TABLE hastlefam.recurring_payments ADD COLUMN cadence varchar(16);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='recurring_payments' AND column_name='day_of_month') THEN
        ALTER TABLE hastlefam.recurring_payments ADD COLUMN day_of_month integer;
    END IF;
END $$;

-- Make account_id and category_id nullable on recurring_payments
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='recurring_payments' AND column_name='account_id') THEN
        ALTER TABLE hastlefam.recurring_payments ALTER COLUMN account_id DROP NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='hastlefam' AND table_name='recurring_payments' AND column_name='category_id') THEN
        ALTER TABLE hastlefam.recurring_payments ALTER COLUMN category_id DROP NOT NULL;
    END IF;
END $$;

-- Data migration: populate new columns from legacy columns (safe with COALESCE)
UPDATE hastlefam.recurring_payments SET title = COALESCE(title, name);
UPDATE hastlefam.recurring_payments SET amount_expected = COALESCE(amount_expected, amount);
UPDATE hastlefam.recurring_payments SET cadence = COALESCE(cadence, period, 'monthly');
UPDATE hastlefam.recurring_payments SET day_of_month = COALESCE(day_of_month, EXTRACT(DAY FROM next_due_date)::int);

-- Make title and cadence NOT NULL after data migration
ALTER TABLE hastlefam.recurring_payments ALTER COLUMN title SET NOT NULL;
ALTER TABLE hastlefam.recurring_payments ALTER COLUMN cadence SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_recurring_due_active ON hastlefam.recurring_payments (next_due_date, is_active);
CREATE INDEX IF NOT EXISTS ix_recurring_owner_id ON hastlefam.recurring_payments (owner_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- Done! All 4 migrations applied.
-- ─────────────────────────────────────────────────────────────────────────────

COMMIT;
