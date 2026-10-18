"""web auth tables (web_login_requests, web_sessions)

Revision ID: c7e2a9d4b1f8
Revises: b5d8e1f3a6c9
Create Date: 2026-10-18 12:00:00.000000

Только новые таблицы: к прогрессии/истории не относятся, *_archive_admin_reset не затрагиваются.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c7e2a9d4b1f8'
down_revision: str | None = 'b5d8e1f3a6c9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'web_login_requests',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('request_id', sa.String(length=32), nullable=False),
        sa.Column('secret_hash', sa.String(length=64), nullable=False),
        sa.Column('code', sa.String(length=4), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
        sa.Column('opened_by_telegram_id', sa.BigInteger(), nullable=True),
        sa.Column('telegram_id', sa.BigInteger(), nullable=True),
        sa.Column('first_name', sa.String(), nullable=True),
        sa.Column('ip_prefix', sa.String(length=64), nullable=True),
        sa.Column('bad_secret_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('poll_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_web_login_requests_request_id', 'web_login_requests', ['request_id'], unique=True)
    op.create_index('ix_web_login_requests_ip_prefix', 'web_login_requests', ['ip_prefix'])
    op.create_table(
        'web_sessions',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('first_name', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('user_agent_hash', sa.String(length=64), nullable=True),
        sa.Column('ip_prefix', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_web_sessions_user_id', 'web_sessions', ['user_id'])
    op.create_index('ix_web_sessions_token_hash', 'web_sessions', ['token_hash'], unique=True)


def downgrade() -> None:
    op.drop_table('web_sessions')
    op.drop_table('web_login_requests')
