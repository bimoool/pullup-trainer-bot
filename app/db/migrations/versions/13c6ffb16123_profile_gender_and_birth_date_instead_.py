"""profile gender and birth_date instead of age

Revision ID: 13c6ffb16123
Revises: b41882a0e3e8
Create Date: 2026-08-11 21:52:38.529342

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '13c6ffb16123'
down_revision: str | None = 'b41882a0e3e8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ВАЖНО: autogenerate также предложил снести все *_archive_v1/*_archive_
# admin_reset таблицы (нет ORM-моделей — ожидаемо, см. историю прошлых
# миграций) и индекс ix_blocks_equipment_item_id (существует в БД, но не
# объявлен index=True на самой ORM-колонке — расхождение старое, не
# связано с этой миграцией). Всё это убрано вручную из черновика.
#
# age — единственная численная колонка, которая устаревает сама по себе
# (человеку исполняется год) — заменена на birth_date, возраст считается
# на лету при показе (app/bot/formatting.py::calculate_age). Не архивируем
# отдельно, в отличие от миграций с историей тренировок: это один скаляр
# на пользователя, а не история, которую нельзя восстановить повторным
# вопросом в анкете.


_gender_enum = postgresql.ENUM('male', 'female', name='gender')


def upgrade() -> None:
    # op.add_column (в отличие от op.create_table) не создаёт enum-тип сам —
    # нужно явно, иначе ALTER TABLE падает с "type gender does not exist".
    _gender_enum.create(op.get_bind(), checkfirst=True)
    op.add_column('users', sa.Column('gender', _gender_enum, nullable=True))
    op.add_column('users', sa.Column('birth_date', sa.Date(), nullable=True))
    op.drop_column('users', 'age')


def downgrade() -> None:
    op.add_column('users', sa.Column('age', sa.SmallInteger(), nullable=True))
    op.drop_column('users', 'birth_date')
    op.drop_column('users', 'gender')
    _gender_enum.drop(op.get_bind(), checkfirst=True)
