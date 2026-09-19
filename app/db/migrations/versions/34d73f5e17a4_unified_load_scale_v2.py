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
    # --- Архивация дореспековских данных -------------------------------
    # Единицы и смысл снаряда меняются несовместимо (мм резины -> кг
    # сопротивления, ветки BAND/ASSISTED упраздняются) — существующие
    # строки нельзя автоматически перевести в новую модель, только
    # выбросить или отложить в сторону. Переносим их в архивные таблицы
    # *_archive_v1 (копия структуры БЕЗ индексов/constraint'ов — это
    # холодное хранилище, не рабочие таблицы) и очищаем активные, прежде
    # чем добавлять новые NOT NULL колонки ниже. Согласовано с
    # пользователем 2026-08-10: на момент миграции в базе только один
    # тестовый аккаунт с этапа живого тестирования,
    # реальных пользователей ещё не было. См. downgrade() — архив не
    # восстанавливается автоматически.
    op.execute("CREATE TABLE IF NOT EXISTS blocks_archive_v1 (LIKE blocks)")
    op.execute("INSERT INTO blocks_archive_v1 SELECT * FROM blocks")
    op.execute("CREATE TABLE IF NOT EXISTS workouts_archive_v1 (LIKE workouts)")
    op.execute("INSERT INTO workouts_archive_v1 SELECT * FROM workouts")
    op.execute("CREATE TABLE IF NOT EXISTS workout_sets_archive_v1 (LIKE workout_sets)")
    op.execute("INSERT INTO workout_sets_archive_v1 SELECT * FROM workout_sets")
    op.execute("CREATE TABLE IF NOT EXISTS baselines_archive_v1 (LIKE baselines)")
    op.execute("INSERT INTO baselines_archive_v1 SELECT * FROM baselines")
    # baselines_archive_v1.equipment_type/branch_result унаследовали СТАРЫЕ
    # enum-типы equipment_type/branch (LIKE копирует и тип колонки) — ниже
    # эти типы удаляются целиком под новые значения, а DROP TYPE ... CASCADE
    # снёс бы вместе с типом и сами архивные колонки (и их данные). Отвязываем
    # архив от типа до дропа: значение остаётся текстом, тип свободен для удаления.
    op.execute("ALTER TABLE baselines_archive_v1 ALTER COLUMN equipment_type TYPE text")
    op.execute("ALTER TABLE baselines_archive_v1 ALTER COLUMN branch_result TYPE text")
    # Данные скопированы и подтверждены выше — теперь можно безопасно
    # очистить активные таблицы (CASCADE подчищает FK между ними самими,
    # других зависимых таблиц у этой четвёрки нет).
    op.execute("TRUNCATE TABLE blocks, workouts, workout_sets, baselines RESTART IDENTITY CASCADE")

    # Тот же тестовый аккаунт: строку users не удаляем и не архивируем
    # отдельно (одна строка, не критично) — просто обнуляем анкету и флаг
    # онбординга, чтобы человек прошёл новый (v2) сценарий замера/анкеты
    # с нуля при следующем /start.
    op.execute(
        "UPDATE users SET onboarding_completed_at = NULL, weight_kg = NULL, "
        "height_cm = NULL, age = NULL, timezone = NULL WHERE telegram_id = 65107390",
    )

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
    # archived, not restored on downgrade — *_archive_v1 таблицы и данные
    # из них намеренно остаются как есть (см. upgrade()); откат схемы сюда
    # не пытается вернуть данные назад в активные таблицы. Если понадобится
    # восстановить дореспековские записи — доставать вручную из архивных
    # таблиц, они никуда не делись.
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
