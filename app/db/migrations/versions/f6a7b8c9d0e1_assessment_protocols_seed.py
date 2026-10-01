"""seed assessment protocols (Tests hub)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-02 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f6a7b8c9d0e1'
down_revision: str | None = 'e5f6a7b8c9d0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Чисто данные, аддитивно: стартовый набор тестов (CRIMPD Tests hub, #260). Схема не
# меняется; вставка идемпотентна (по имени), повторный прогон ничего не дублирует.
# downgrade удаляет только засеянные протоколы, у которых нет ни одного результата.

_PROTOCOLS = [
    (
        'Максимум подтягиваний', 'reps', 'Подтягивания',
        ('Максимум подтягиваний за один подход: хват сверху, без раскачки, подбородок выше перекладины. '
         'Отдохнувший, после разминки.'),
    ),
    (
        'Вис на перекладине, сек', 'time', 'Хват',
        ('Сколько секунд вы удерживаете вис на перекладине до отказа. Засекайте от момента, '
         'когда ноги оторвались от опоры.'),
    ),
    (
        'Подтягивания с весом, кг', 'weight', 'Подтягивания',
        ('Максимальный дополнительный вес (кг), с которым вы делаете чистое подтягивание. '
         'Записывайте только вес отягощения, без собственного.'),
    ),
]


def upgrade() -> None:
    insert = sa.text(
        "INSERT INTO assessment_protocols (name, metric_type, category, description) "
        "SELECT :name, CAST(:metric AS mp_metric_type), :category, :description "
        "WHERE NOT EXISTS (SELECT 1 FROM assessment_protocols WHERE name = :name)"
    )
    for name, metric_type, category, description in _PROTOCOLS:
        op.execute(insert.bindparams(name=name, metric=metric_type, category=category, description=description))


def downgrade() -> None:
    delete = sa.text(
        "DELETE FROM assessment_protocols WHERE name = :name "
        "AND NOT EXISTS (SELECT 1 FROM assessment_results r WHERE r.protocol_id = assessment_protocols.id)"
    )
    for name, *_ in _PROTOCOLS:
        op.execute(delete.bindparams(name=name))
