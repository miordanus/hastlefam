"""FoodOps Home schema — inventory, shopping list, raw inputs, receipts

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-07

Adds the FoodOps Home tables into the hastlefam schema, reusing households/users.
Milestone 1 writes food_products, inventory_items, inventory_events,
shopping_list_items, raw_inputs. receipts/receipt_items are modeled now but not
written until the receipt-parsing milestone.
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS hastlefam.food_products (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          canonical_name VARCHAR(255) NOT NULL UNIQUE,
          category VARCHAR(32) NOT NULL DEFAULT 'unknown',
          default_unit VARCHAR(32),
          shelf_life_days INTEGER,
          is_always_in_stock BOOLEAN NOT NULL DEFAULT FALSE,
          min_stock_status VARCHAR(32),
          created_at TIMESTAMPTZ DEFAULT now()
        );
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS hastlefam.raw_inputs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL REFERENCES hastlefam.households(id),
          user_id UUID REFERENCES hastlefam.users(id),
          input_type VARCHAR(32) NOT NULL DEFAULT 'text',
          raw_text TEXT NOT NULL,
          parsed_json JSONB,
          parsing_status VARCHAR(16) NOT NULL DEFAULT 'pending',
          created_at TIMESTAMPTZ DEFAULT now()
        );
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS hastlefam.inventory_items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL REFERENCES hastlefam.households(id),
          product_id UUID NOT NULL REFERENCES hastlefam.food_products(id),
          location VARCHAR(16) NOT NULL DEFAULT 'unknown',
          status VARCHAR(16) NOT NULL DEFAULT 'in_stock',
          quantity NUMERIC(12,3),
          unit VARCHAR(32),
          expires_at DATE,
          last_confirmed_at TIMESTAMPTZ,
          confidence VARCHAR(16) NOT NULL DEFAULT 'medium',
          notes TEXT,
          updated_at TIMESTAMPTZ DEFAULT now(),
          CONSTRAINT uq_inventory_household_product_location UNIQUE (household_id, product_id, location)
        );
        CREATE INDEX IF NOT EXISTS ix_inventory_items_household ON hastlefam.inventory_items (household_id);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS hastlefam.inventory_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL REFERENCES hastlefam.households(id),
          user_id UUID REFERENCES hastlefam.users(id),
          product_id UUID REFERENCES hastlefam.food_products(id),
          raw_product_name VARCHAR(255),
          event_type VARCHAR(32) NOT NULL,
          quantity NUMERIC(12,3),
          unit VARCHAR(32),
          status VARCHAR(16),
          location VARCHAR(16),
          happened_at TIMESTAMPTZ DEFAULT now(),
          source VARCHAR(16) NOT NULL DEFAULT 'text',
          raw_input_id UUID REFERENCES hastlefam.raw_inputs(id),
          confidence VARCHAR(16) NOT NULL DEFAULT 'medium',
          notes TEXT,
          created_at TIMESTAMPTZ DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_inventory_events_household_happened
          ON hastlefam.inventory_events (household_id, happened_at);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS hastlefam.shopping_list_items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL REFERENCES hastlefam.households(id),
          product_id UUID REFERENCES hastlefam.food_products(id),
          raw_product_name VARCHAR(255),
          quantity NUMERIC(12,3),
          unit VARCHAR(32),
          priority VARCHAR(16) NOT NULL DEFAULT 'normal',
          reason VARCHAR(32),
          status VARCHAR(16) NOT NULL DEFAULT 'open',
          source VARCHAR(16) NOT NULL DEFAULT 'text',
          created_by UUID REFERENCES hastlefam.users(id),
          created_at TIMESTAMPTZ DEFAULT now(),
          updated_at TIMESTAMPTZ DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_shopping_list_household_status
          ON hastlefam.shopping_list_items (household_id, status);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS hastlefam.receipts (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL REFERENCES hastlefam.households(id),
          store_name VARCHAR(255),
          purchased_at TIMESTAMPTZ,
          source_type VARCHAR(32),
          raw_text TEXT,
          total_amount NUMERIC(14,2),
          currency VARCHAR(8) NOT NULL DEFAULT 'RUB',
          parsing_status VARCHAR(16) NOT NULL DEFAULT 'pending',
          created_at TIMESTAMPTZ DEFAULT now()
        );
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS hastlefam.receipt_items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          receipt_id UUID NOT NULL REFERENCES hastlefam.receipts(id),
          raw_name VARCHAR(255) NOT NULL,
          product_id UUID REFERENCES hastlefam.food_products(id),
          quantity NUMERIC(12,3),
          unit VARCHAR(32),
          price_total NUMERIC(14,2),
          price_per_unit NUMERIC(14,2),
          confidence VARCHAR(16) NOT NULL DEFAULT 'medium',
          needs_review BOOLEAN NOT NULL DEFAULT FALSE,
          created_at TIMESTAMPTZ DEFAULT now()
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hastlefam.receipt_items;")
    op.execute("DROP TABLE IF EXISTS hastlefam.receipts;")
    op.execute("DROP TABLE IF EXISTS hastlefam.shopping_list_items;")
    op.execute("DROP TABLE IF EXISTS hastlefam.inventory_events;")
    op.execute("DROP TABLE IF EXISTS hastlefam.inventory_items;")
    op.execute("DROP TABLE IF EXISTS hastlefam.raw_inputs;")
    op.execute("DROP TABLE IF EXISTS hastlefam.food_products;")
