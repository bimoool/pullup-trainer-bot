"""Canonical registration of EVERY ORM model into Base.metadata.

SQLAlchemy only knows a table once the module that declares it has been imported. The schema is split across
app.db.models (legacy/bot-era + users/subscriptions) and app.db.models_program (multi-program v2, issue #160), and
nothing forces the second one to be imported: the web process happens to load it through routes_v2*, the bot
process never did. Code that reasons about the WHOLE schema from metadata (Alembic autogenerate, the staging
«🧪 Fresh reset» drift/FK guards) must therefore import `metadata` from here, never `Base.metadata` directly — a
partially registered metadata silently describes a different schema depending on the process's import graph
(incident: the staging bot's fresh-reset dry run reported 21 v2 tables "missing", see ENGINEERING_NOTES.md).

A new model module MUST be added to the import list below.
"""

from app.db import (
    models,  # noqa: F401 — registers the legacy/bot tables
    models_program,  # noqa: F401 — registers the multi-program (v2) tables
)
from app.db.base import Base

metadata = Base.metadata
