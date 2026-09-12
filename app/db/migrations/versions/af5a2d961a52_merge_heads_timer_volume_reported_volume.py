"""merge heads: timer volume + reported volume

Revision ID: af5a2d961a52
Revises: a9d4e6f2b8c1, d1e5f9a3c7b8
Create Date: 2026-09-12 11:13:04.937269

"""
from collections.abc import Sequence

revision: str = 'af5a2d961a52'
down_revision: str | None = ('a9d4e6f2b8c1', 'd1e5f9a3c7b8')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
