from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002_mobile'
down_revision = '0001_alpha'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'delivery_jobs',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('city_id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('version', sa.BigInteger(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=12), server_default='pending', nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('error', sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(['city_id'], ['cities.id'], ),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('city_id', 'version', 'client_id', name='uq_delivery_event_client')
    )
    op.create_index('ix_delivery_client', 'delivery_jobs', ['client_id'], unique=False)
    op.create_index('ix_delivery_expiry', 'delivery_jobs', ['expires_at'], unique=False)
    op.create_index('ix_delivery_pending', 'delivery_jobs', ['status', 'next_attempt_at', 'id'], unique=False)
    op.add_column('cities', sa.Column('version', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('cities', sa.Column('event_id', sa.String(length=80), nullable=True))
    op.add_column('cities', sa.Column('event_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('cities', sa.Column('event_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('cities', sa.Column('summary', sa.Text(), nullable=True))
    op.add_column('cities', sa.Column('listener_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('cities', sa.Column('source_chat_id', sa.BigInteger(), nullable=True))
    op.add_column('cities', sa.Column('last_message_id', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('cities', sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('cities', sa.Column('uncertain', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('classification_history', sa.Column('status', sa.String(length=12), server_default='done', nullable=False))
    op.add_column('classification_history', sa.Column('attempts', sa.Integer(), server_default='0', nullable=False))
    op.add_column('classification_history', sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('classification_history', sa.Column('error', sa.String(length=80), nullable=True))
    op.alter_column('classification_history', 'first_answer',
               existing_type=sa.TEXT(),
               nullable=True)
    op.alter_column('classification_history', 'final_answer',
               existing_type=sa.TEXT(),
               nullable=True)
    op.create_index('ix_history_processing', 'classification_history', ['city_id', 'status', 'source_message_id'], unique=False)
    op.add_column('clients', sa.Column('installation_id', sa.UUID(), nullable=True))
    op.add_column('clients', sa.Column('credential_hash', sa.String(length=64), nullable=True))
    op.add_column('clients', sa.Column('app_check_app_id', sa.Text(), nullable=True))
    op.add_column('clients', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('clients', sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_clients_deactivated', 'clients', ['deactivated_at'], unique=False)
    op.create_unique_constraint('uq_clients_installation', 'clients', ['installation_id'])
    op.execute("INSERT INTO cities (code, name) VALUES ('dnipro', 'Дніпро') ON CONFLICT (code) DO NOTHING")


def downgrade():
    op.drop_constraint('uq_clients_installation', 'clients', type_='unique')
    op.execute("UPDATE classification_history SET first_answer = COALESCE(first_answer, ''), final_answer = COALESCE(final_answer, '')")
    op.drop_index('ix_clients_deactivated', table_name='clients')
    op.drop_column('clients', 'deactivated_at')
    op.drop_column('clients', 'last_seen_at')
    op.drop_column('clients', 'app_check_app_id')
    op.drop_column('clients', 'credential_hash')
    op.drop_column('clients', 'installation_id')
    op.drop_index('ix_history_processing', table_name='classification_history')
    op.alter_column('classification_history', 'final_answer',
               existing_type=sa.TEXT(),
               nullable=False)
    op.alter_column('classification_history', 'first_answer',
               existing_type=sa.TEXT(),
               nullable=False)
    op.drop_column('classification_history', 'error')
    op.drop_column('classification_history', 'next_attempt_at')
    op.drop_column('classification_history', 'attempts')
    op.drop_column('classification_history', 'status')
    op.drop_column('cities', 'uncertain')
    op.drop_column('cities', 'context')
    op.drop_column('cities', 'last_message_id')
    op.drop_column('cities', 'source_chat_id')
    op.drop_column('cities', 'listener_seen_at')
    op.drop_column('cities', 'summary')
    op.drop_column('cities', 'event_expires_at')
    op.drop_column('cities', 'event_at')
    op.drop_column('cities', 'event_id')
    op.drop_column('cities', 'version')
    op.drop_index('ix_delivery_pending', table_name='delivery_jobs')
    op.drop_index('ix_delivery_expiry', table_name='delivery_jobs')
    op.drop_index('ix_delivery_client', table_name='delivery_jobs')
    op.drop_table('delivery_jobs')
