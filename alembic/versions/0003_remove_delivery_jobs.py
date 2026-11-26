from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_remove_delivery_jobs"
down_revision = "0002_mobile"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("delivery_jobs")
    op.drop_constraint("uq_clients_installation", "clients", type_="unique")
    op.drop_column("clients", "app_check_app_id")
    op.drop_column("clients", "credential_hash")
    op.drop_column("clients", "installation_id")
    op.drop_column("cities", "uncertain")
    op.drop_column("cities", "event_expires_at")
    op.drop_column("cities", "version")


def downgrade():
    op.add_column("cities", sa.Column("version", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column("cities", sa.Column("event_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cities", sa.Column("uncertain", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("clients", sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("clients", sa.Column("credential_hash", sa.String(length=64), nullable=True))
    op.add_column("clients", sa.Column("app_check_app_id", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_clients_installation", "clients", ["installation_id"])
    op.create_table(
        "delivery_jobs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("error", sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("city_id", "version", "client_id", name="uq_delivery_event_client"),
    )
    op.create_index("ix_delivery_client", "delivery_jobs", ["client_id"], unique=False)
    op.create_index("ix_delivery_expiry", "delivery_jobs", ["expires_at"], unique=False)
    op.create_index("ix_delivery_pending", "delivery_jobs", ["status", "next_attempt_at", "id"], unique=False)
