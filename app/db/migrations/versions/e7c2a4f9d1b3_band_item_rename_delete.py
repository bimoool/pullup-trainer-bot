"""band item rename/delete

Revision ID: e7c2a4f9d1b3
Revises: c2b8e6a4f1d9
Create Date: 2026-09-16 17:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e7c2a4f9d1b3'
down_revision: str | None = 'c2b8e6a4f1d9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# issue #148 — резину можно теперь удалить (PATCH/DELETE
# /api/equipment/band-items/{id}), поэтому FK с blocks/elective_workouts
# больше не может быть RESTRICT (дефолт без ON DELETE): попытка удалить
# резину, уже использованную хотя бы в одной тренировке/факультативе,
# упала бы IntegrityError. ON DELETE SET NULL плюс снапшот названия
# (equipment_item_name, заполняется репозиторием на запись блока, здесь —
# только бэкфилл текущим именем для уже существующих строк, см. ниже)
# — история переживает и удаление, и последующее переименование резины.
#
# Имя FK-констрейнта blocks.equipment_item_id известно точно — задано
# явно в 5276000c6613 (fk_blocks_equipment_item_id). У elective_workouts
# констрейнт создан inline через sa.ForeignKeyConstraint без явного имени
# (391830b06fff) — там его дал Postgres по умолчанию
# (`<table>_<column>_fkey`); ищем/дропаем его по факту через pg_constraint,
# а не полагаемся на строку с этим именем "на глаз" (тот же принцип, что и
# остальные схемные изменения проекта — не гадать на боевых данных).


def upgrade() -> None:
    op.add_column('blocks', sa.Column('equipment_item_name', sa.Text(), nullable=True))
    op.add_column(
        'blocks_archive_admin_reset', sa.Column('equipment_item_name', sa.Text(), nullable=True),
    )
    op.add_column('elective_workouts', sa.Column('equipment_item_name', sa.Text(), nullable=True))

    # Бэкфилл — до этой миграции резину нельзя было переименовать, значит
    # текущее equipment_items.name РАВНО названию на момент любой уже
    # существующей тренировки/факультатива.
    op.execute(
        "UPDATE blocks b SET equipment_item_name = ei.name "
        "FROM equipment_items ei "
        "WHERE b.equipment_item_id = ei.id AND b.equipment_item_name IS NULL",
    )
    op.execute(
        "UPDATE elective_workouts w SET equipment_item_name = ei.name "
        "FROM equipment_items ei "
        "WHERE w.equipment_item_id = ei.id AND w.equipment_item_name IS NULL",
    )

    op.drop_constraint('fk_blocks_equipment_item_id', 'blocks', type_='foreignkey')
    op.create_foreign_key(
        'fk_blocks_equipment_item_id', 'blocks', 'equipment_items', ['equipment_item_id'], ['id'],
        ondelete='SET NULL',
    )

    op.execute(
        "DO $$ "
        "DECLARE fk_name text; "
        "BEGIN "
        "  SELECT conname INTO fk_name FROM pg_constraint "
        "  WHERE conrelid = 'elective_workouts'::regclass "
        "    AND confrelid = 'equipment_items'::regclass AND contype = 'f'; "
        "  IF fk_name IS NOT NULL THEN "
        "    EXECUTE format('ALTER TABLE elective_workouts DROP CONSTRAINT %I', fk_name); "
        "  END IF; "
        "END $$;",
    )
    op.create_foreign_key(
        'fk_elective_workouts_equipment_item_id', 'elective_workouts', 'equipment_items',
        ['equipment_item_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_elective_workouts_equipment_item_id', 'elective_workouts', type_='foreignkey',
    )
    op.create_foreign_key(
        'elective_workouts_equipment_item_id_fkey', 'elective_workouts', 'equipment_items',
        ['equipment_item_id'], ['id'],
    )

    op.drop_constraint('fk_blocks_equipment_item_id', 'blocks', type_='foreignkey')
    op.create_foreign_key(
        'fk_blocks_equipment_item_id', 'blocks', 'equipment_items', ['equipment_item_id'], ['id'],
    )

    op.drop_column('elective_workouts', 'equipment_item_name')
    op.drop_column('blocks_archive_admin_reset', 'equipment_item_name')
    op.drop_column('blocks', 'equipment_item_name')
