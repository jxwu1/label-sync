"""add inventory events tables and stockpile analytics columns

Revision ID: 7f998b4f11ff
Revises: c80afeb49bae
Create Date: 2026-05-05 19:08:40.852970

阶段 4 PR 4.1：进销存事件表 + 客户/供应商主档 + 老外客人记录 +
导入向导配置 + stockpile 加 8 个分析字段。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f998b4f11ff"
down_revision: Union[str, Sequence[str], None] = "c80afeb49bae"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === stockpile 加分析字段 ===
    with op.batch_alter_table("stockpile") as batch:
        batch.add_column(sa.Column("product_name_zh", sa.Text(), nullable=True))
        batch.add_column(sa.Column("product_name_local", sa.Text(), nullable=True))
        batch.add_column(sa.Column("erp_category_raw", sa.Text(), nullable=True))
        batch.add_column(sa.Column("erp_category_code", sa.Text(), nullable=True))
        batch.add_column(sa.Column("manual_grade", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("manual_category", sa.Text(), nullable=True))
        batch.add_column(sa.Column("auto_category", sa.Text(), nullable=True))
        batch.add_column(sa.Column("auto_category_computed_at", sa.Text(), nullable=True))

    # === customers ===
    op.create_table(
        "customers",
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("customer_name", sa.Text(), nullable=False),
        sa.Column("customer_type", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("customer_id"),
    )
    op.create_index("idx_customers_type", "customers", ["customer_type"])

    # === suppliers ===
    op.create_table(
        "suppliers",
        sa.Column("supplier_id", sa.Text(), nullable=False),
        sa.Column("supplier_name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("supplier_id"),
    )

    # === inventory_events ===
    op.create_table(
        "inventory_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_at", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("product_barcode", sa.Text(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("discount_pct", sa.Float(), nullable=True),
        sa.Column("document_no", sa.Text(), nullable=True),
        sa.Column("shipping_doc", sa.Text(), nullable=True),
        sa.Column("customer_id", sa.Text(), nullable=True),
        sa.Column("supplier_id", sa.Text(), nullable=True),
        sa.Column("warehouse", sa.Text(), nullable=True),
        sa.Column("erp_category_raw", sa.Text(), nullable=True),
        sa.Column("erp_category_code", sa.Text(), nullable=True),
        sa.Column("manual_grade", sa.Integer(), nullable=True),
        sa.Column(
            "imported_at",
            sa.Text(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_type",
            "document_no",
            "shipping_doc",
            "product_barcode",
            "event_at",
            "qty",
            "unit_price",
            name="uq_inventory_events",
        ),
    )
    op.create_index(
        "idx_events_barcode_at",
        "inventory_events",
        ["product_barcode", "event_at"],
    )
    op.create_index("idx_events_customer", "inventory_events", ["customer_id"])
    op.create_index("idx_events_supplier", "inventory_events", ["supplier_id"])
    op.create_index(
        "idx_events_type_at", "inventory_events", ["event_type", "event_at"]
    )

    # === foreign_customer_records ===
    op.create_table(
        "foreign_customer_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("record_month", sa.Text(), nullable=False),
        sa.Column("amount_due", sa.Float(), nullable=True),
        sa.Column("tax_number", sa.Text(), nullable=True),
        sa.Column("payment_date", sa.Text(), nullable=True),
        sa.Column("shipping_date", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.Text(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "customer_id", "record_month", name="uq_foreign_customer_records"
        ),
    )
    op.create_index("idx_fcr_month", "foreign_customer_records", ["record_month"])

    # === import_profiles ===
    op.create_table(
        "import_profiles",
        sa.Column("profile_name", sa.Text(), nullable=False),
        sa.Column("column_mapping_json", sa.Text(), nullable=False),
        sa.Column("last_used_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("profile_name"),
    )


def downgrade() -> None:
    op.drop_table("import_profiles")
    op.drop_index("idx_fcr_month", table_name="foreign_customer_records")
    op.drop_table("foreign_customer_records")
    op.drop_index("idx_events_type_at", table_name="inventory_events")
    op.drop_index("idx_events_supplier", table_name="inventory_events")
    op.drop_index("idx_events_customer", table_name="inventory_events")
    op.drop_index("idx_events_barcode_at", table_name="inventory_events")
    op.drop_table("inventory_events")
    op.drop_table("suppliers")
    op.drop_index("idx_customers_type", table_name="customers")
    op.drop_table("customers")
    with op.batch_alter_table("stockpile") as batch:
        batch.drop_column("auto_category_computed_at")
        batch.drop_column("auto_category")
        batch.drop_column("manual_category")
        batch.drop_column("manual_grade")
        batch.drop_column("erp_category_code")
        batch.drop_column("erp_category_raw")
        batch.drop_column("product_name_local")
        batch.drop_column("product_name_zh")
