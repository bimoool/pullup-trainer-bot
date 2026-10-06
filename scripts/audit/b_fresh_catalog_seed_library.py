"""Audit-only wrapper: imports all models (so FK 'users' resolves) then runs scripts/seed_exercise_library.py::main unchanged."""
import asyncio
import sys

import app.db.models
import app.db.models_program  # noqa: F401

sys.path.insert(0, "scripts")
import seed_exercise_library

asyncio.run(seed_exercise_library.main())
