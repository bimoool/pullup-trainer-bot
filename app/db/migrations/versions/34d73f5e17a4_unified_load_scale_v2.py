"""unified load scale v2

Revision ID: 34d73f5e17a4
Revises: 6dbcfb436c46
Create Date: 2026-08-09 11:53:37.059841

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '34d73f5e17a4'
down_revision: str | None = '6dbcfb436c46'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# op.add_column() с sa.Enum() не создаёt тип сам по себе (в отличие от
# create_table, где SQLAlchemy это делает неявно) — типы создаём/удаляем
# явно через .create()/.drop(), а в add_column передаём create_type=False,
# чтобы не пытаться создать их повторно.
_new_equipment_type = postgresql.ENUM(
    'band', 'bodyweight', 'weight', 'australian', name='equipment_type',
)
_exercise_type = postgresql.ENUM('pull_ups', name='exercise_type')
_old_equipment_type = postgresql.ENUM('band', 'weight', name='equipment_type')
_old_branch_type = postgresql.ENUM('band', 'assisted', name='branch')


def upgrade() -> None:
    op.drop_column('baselines', 'equipment_type')
    op.drop_column('baselines', 'branch_result')
    op.drop_column('baselines', 'weight_kg')
    op.drop_column('baselines', 'band_thickness_mm')
    op.drop_column('users', 'branch')
    # Старые типы equipment_type (band/weight) и branch (band/assisted)
    # остаются в базе после drop_column — их надо снести явно, прежде чем
    # завести НОВЫЙ equipment_type (band/bodyweight/weight/australian):
    # имя типа совпадает со старым, а набор значений — нет.
    op.execute("DROP TYPE IF EXISTS equipment_type")
    op.execute("DROP TYPE IF EXISTS branch")

    bind = op.get_bind()
    _new_equipment_type.create(bind, checkfirst=True)
    _exercise_type.create(bind, checkfirst=True)

    op.add_column(
        'blocks',
        sa.Column(
            'equipment_type',
            postgresql.ENUM('band', 'bodyweight', 'weight', 'australian', name='equipment_type', create_type=False),
            nullable=False,
        ),
    )
    op.add_column('blocks', sa.Column('equipment_value', sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column('blocks', sa.Column('transition_failed', sa.Boolean(), server_default='false', nullable=False))
    op.drop_column('blocks', 'weight_kg')
    op.drop_column('blocks', 'band_thickness_mm')
    op.add_column('workouts', sa.Column('participates_in_cascade', sa.Boolean(), server_default='true', nullable=False))
    op.add_column(
        'workouts',
        sa.Column(
            'exercise_type',
            postgresql.ENUM('pull_ups', name='exercise_type', create_type=False),
            server_default='pull_ups',
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('workouts', 'exercise_type')
    op.drop_column('workouts', 'participates_in_cascade')
    op.drop_column('blocks', 'transition_failed')
    op.drop_column('blocks', 'equipment_value')
    op.drop_column('blocks', 'equipment_type')
    op.add_column('blocks', sa.Column('band_thickness_mm', sa.NUMERIC(precision=4, scale=1), autoincrement=False, nullable=True))
    op.add_column('blocks', sa.Column('weight_kg', sa.NUMERIC(precision=5, scale=2), autoincrement=False, nullable=True))

    # Как и на upgrade — снести НОВЫЙ equipment_type (4 значения) и
    # exercise_type перед тем, как заводить обратно старые branch/
    # equipment_type (2 значения) под теми же именами.
    op.execute("DROP TYPE IF EXISTS equipment_type")
    op.execute("DROP TYPE IF EXISTS exercise_type")

    bind = op.get_bind()
    _old_equipment_type.create(bind, checkfirst=True)
    _old_branch_type.create(bind, checkfirst=True)

    op.add_column(
        'users',
        sa.Column('branch', postgresql.ENUM('band', 'assisted', name='branch', create_type=False), autoincrement=False, nullable=True),
    )
    op.add_column('baselines', sa.Column('band_thickness_mm', sa.NUMERIC(precision=4, scale=1), autoincrement=False, nullable=True))
    op.add_column('baselines', sa.Column('weight_kg', sa.NUMERIC(precision=5, scale=2), autoincrement=False, nullable=True))
    op.add_column(
        'baselines',
        sa.Column('branch_result', postgresql.ENUM('band', 'assisted', name='branch', create_type=False), autoincrement=False, nullable=False),
    )
    op.add_column(
        'baselines',
        sa.Column('equipment_type', postgresql.ENUM('band', 'weight', name='equipment_type', create_type=False), autoincrement=False, nullable=False),
    )
