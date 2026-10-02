"""curated collections (playlists)

Revision ID: 9e3f1a4b6c80
Revises: 8d2e0f3a5b79
Create Date: 2026-10-02 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '9e3f1a4b6c80'
down_revision: str | None = '8d2e0f3a5b79'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Подборки (issue #271). Аддитивно: две новые таблицы, старый код их не читает.
# Сид: одна опубликованная подборка «Начни с подтягиваний» из уже существующих
# программ каталога (все программы с категорией pull_ups, в порядке id). Если таких
# программ ещё нет (свежая БД до backfill_multi_program), подборка создаётся без
# элементов и на Главной не показывается; после backfill её наполняет
# `python scripts/seed_collections.py` (идемпотентно).

_SLUG = 'start-with-pull-ups'
_TITLE = 'Начни с подтягиваний'
_DESCRIPTION = (
    'Программы Турникмэна, с которых удобно начать: объём и сила в подтягиваниях '
    'с понятной прогрессией.'
)


def upgrade() -> None:
    op.create_table(
        'collections',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('author_label', sa.String(length=100), server_default='Турникмэн', nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_published', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('slug', name='uq_collections_slug'),
    )
    op.create_table(
        'collection_items',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('collection_id', sa.BigInteger(), sa.ForeignKey('collections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('program_id', sa.BigInteger(), sa.ForeignKey('programs.id', ondelete='CASCADE'), nullable=True),
        sa.Column('exercise_id', sa.BigInteger(), sa.ForeignKey('exercises.id', ondelete='CASCADE'), nullable=True),
        sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    )
    op.create_index('ix_collection_items_collection_id', 'collection_items', ['collection_id'])

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO collections (slug, title, description, author_label, sort_order, is_published) "
            "VALUES (:slug, :title, :description, 'Турникмэн', 0, true)"
        ),
        {'slug': _SLUG, 'title': _TITLE, 'description': _DESCRIPTION},
    )
    bind.execute(
        sa.text(
            "INSERT INTO collection_items (collection_id, program_id, position) "
            "SELECT (SELECT id FROM collections WHERE slug = :slug), p.id, "
            "(ROW_NUMBER() OVER (ORDER BY p.id)) - 1 "
            "FROM programs p WHERE p.category = 'pull_ups'"
        ),
        {'slug': _SLUG},
    )


def downgrade() -> None:
    op.drop_index('ix_collection_items_collection_id', table_name='collection_items')
    op.drop_table('collection_items')
    op.drop_table('collections')
