#!/usr/bin/env python3
"""Refresh docs/PROJECT_STATUS.md from GitHub + git (thin wrapper over `orch.py status`).

    python scripts/update_project_status.py            # rewrite docs/PROJECT_STATUS.md
    python scripts/update_project_status.py --print    # only print, write nothing ("where are we?")

Needs `gh auth login` and a clone of the repo; works from any computer.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import orch

if __name__ == "__main__":
    extra = sys.argv[1:]
    if "--print" in extra:
        sys.exit(orch.main(["where"]))
    sys.exit(orch.main(["status", *extra]))
