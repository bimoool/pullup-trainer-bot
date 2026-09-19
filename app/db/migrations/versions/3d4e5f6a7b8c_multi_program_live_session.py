"""multi program live session

Revision ID: 3d4e5f6a7b8c
Revises: 2b3c4d5e6f7a
Create Date: 2026-09-19 14:05:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '3d4e5f6a7b8c'
down_revision: str | None = '2b3c4d5e6f7a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Живая (server-driven) сессия тренировки поверх волны 1 (issue #165,
# продолжение) — полностью аддитивно, ни одна существующая колонка/таблица
# не меняется: старый одноразовый POST /api/v2/sessions ("записать уже
# выполненную тренировку целиком") продолжает работать без изменений,
# новые колонки для него остаются NULL/дефолтными.
#
# training_sessions.client_session_id — идемпотентность старта живой сессии
# по офлайн-контракту (клиент генерирует UUID до первого запроса к серверу).
# UNIQUE, но NULL допустим и не считается конфликтующим друг с другом в
# Postgres (несколько NULL проходят UNIQUE) — старые/бэкфилленные записи,
# которые никогда не устанавливают это поле, никак не мешают друг другу.
#
# training_sessions.phase_name/phase_ends_at/current_block_index/
# current_set_number/phase_index — состояние машины фаз (см.
# app.domain.live_session): get_ready -> go -> rest по кругу внутри блока,
# done — сессия завершена. server_default='done' для phase_name — так уже
# существующие/бэкфилленные строки (созданные до этой миграции, никогда не
# бывшие "живыми") остаются консистентными без отдельного backfill-запроса.
#
# set_logs.session_id/set_index — денормализация (session_id уже доступен
# транзитивно через session_blocks.session_id) ради простого upsert-ключа
# батч-эндпоинта: (session_id, set_index) без JOIN на session_blocks. UNIQUE
# на паре NULL-safe тем же приёмом, что и client_session_id выше — старые
# строки (обе колонки NULL) друг другу не мешают.
#
# program_inclusions.initial_progression_state — снимок progression_state
# НА МОМЕНТ создания инклюзии, отдельно от progression_state (живое,
# мутируемое значение). Нужен для progression_cascade: воспроизвести всю
# цепочку тренировок заново с известной точки старта при правке исторической
# сессии, не полагаясь на снимки на каждую отдельную сессию (которых нет).


def upgrade() -> None:
    bind = op.get_bind()
    session_phase_enum = postgresql.ENUM('get_ready', 'go', 'rest', 'done', name='mp_session_phase')
    session_phase_enum.create(bind, checkfirst=True)

    op.add_column(
        'training_sessions', sa.Column('client_session_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint(
        'uq_training_sessions_client_session_id', 'training_sessions', ['client_session_id'],
    )
    op.add_column(
        'training_sessions',
        sa.Column(
            'phase_name',
            postgresql.ENUM('get_ready', 'go', 'rest', 'done', name='mp_session_phase', create_type=False),
            server_default='done', nullable=False,
        ),
    )
    op.add_column('training_sessions', sa.Column('phase_ends_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'training_sessions',
        sa.Column('current_block_index', sa.SmallInteger(), server_default='0', nullable=False),
    )
    op.add_column(
        'training_sessions',
        sa.Column('current_set_number', sa.SmallInteger(), server_default='1', nullable=False),
    )
    # Явный монотонный счётчик переходов фазы (не выводится из
    # block_index/set_number/phase_name на лету) — офлайн-контракт требует
    # сравнивать "клиентский expected_phase_index" с "серверным текущим" одним
    # int, без риска, что вычисленный на лету индекс разойдётся с тем, что
    # клиент видел в предыдущем ответе (см. app.services.live_session).
    op.add_column(
        'training_sessions', sa.Column('phase_index', sa.SmallInteger(), server_default='0', nullable=False),
    )

    op.add_column('set_logs', sa.Column('session_id', sa.BigInteger(), nullable=True))
    op.create_index(op.f('ix_set_logs_session_id'), 'set_logs', ['session_id'], unique=False)
    op.create_foreign_key(
        'fk_set_logs_session_id', 'set_logs', 'training_sessions', ['session_id'], ['id'], ondelete='CASCADE',
    )
    op.add_column('set_logs', sa.Column('set_index', sa.SmallInteger(), nullable=True))
    op.create_unique_constraint('uq_set_logs_session_set_index', 'set_logs', ['session_id', 'set_index'])

    op.add_column(
        'program_inclusions',
        sa.Column(
            'initial_progression_state', postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}', nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('program_inclusions', 'initial_progression_state')

    op.drop_constraint('uq_set_logs_session_set_index', 'set_logs', type_='unique')
    op.drop_column('set_logs', 'set_index')
    op.drop_constraint('fk_set_logs_session_id', 'set_logs', type_='foreignkey')
    op.drop_index(op.f('ix_set_logs_session_id'), table_name='set_logs')
    op.drop_column('set_logs', 'session_id')

    op.drop_column('training_sessions', 'phase_index')
    op.drop_column('training_sessions', 'current_set_number')
    op.drop_column('training_sessions', 'current_block_index')
    op.drop_column('training_sessions', 'phase_ends_at')
    # phase_name дропается ДО DROP TYPE mp_session_phase ниже — тот же
    # порядок, что уже задокументирован в 34d73f5e17a4_unified_load_scale_v2
    # (снести колонку, использующую тип, прежде чем сносить сам тип).
    op.drop_column('training_sessions', 'phase_name')
    op.drop_constraint('uq_training_sessions_client_session_id', 'training_sessions', type_='unique')
    op.drop_column('training_sessions', 'client_session_id')

    op.execute('DROP TYPE IF EXISTS mp_session_phase')
