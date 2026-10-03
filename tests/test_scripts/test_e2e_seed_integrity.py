"""Guard (wave 13, E2E integrity): the E2E seed registry cannot silently drift from the specs.

* every `seed <scenario> <telegram_id>` line of scripts/e2e_seed_all.sh uses a known scenario;
* telegram ids are unique across the whole registry (two seeds on one id = the later one wipes the first);
* every literal telegram id in webapp-frontend/e2e/** is seeded (a spec pointing at an unseeded id
  would run against a non-onboarded user and fail confusingly, or worse pass vacuously);
* no `test.fixme` / unconditional `test.skip` in scenarios: quarantined specs hide regressions.
"""

from __future__ import annotations

import collections
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED_ALL = ROOT / "scripts" / "e2e_seed_all.sh"
E2E = ROOT / "webapp-frontend" / "e2e"
# Seeded by absence: not_onboarded.spec.ts needs a user with NO row in users.
UNSEEDED_ON_PURPOSE = {"900001"}


def _expanded_seeds() -> list[tuple[str, str]]:
    """Run the registry with `seed` stubbed to print its arguments (expands loops and arithmetic)."""
    body = "\n".join(
        line for line in SEED_ALL.read_text().splitlines()
        if not line.startswith(("set -", "export PYTHONPATH", "PY=", "seed()"))
    )
    script = 'seed() { echo "$1 $2"; }\n' + body
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout
    return [tuple(line.split()) for line in out.splitlines() if line.strip()]  # type: ignore[misc]


def test_seed_registry_scenarios_exist_and_ids_unique() -> None:
    from scripts.e2e_seed import SCENARIOS

    seeds = _expanded_seeds()
    assert len(seeds) > 100
    unknown = sorted({name for name, _ in seeds if name not in SCENARIOS})
    assert unknown == [], f"e2e_seed_all.sh uses unknown scenarios: {unknown}"
    by_id: dict[str, list[str]] = collections.defaultdict(list)
    for name, telegram_id in seeds:
        by_id[telegram_id].append(name)
    duplicates = {i: names for i, names in by_id.items() if len(names) > 1}
    assert duplicates == {}, f"telegram ids seeded more than once: {duplicates}"


def test_spec_telegram_ids_are_seeded() -> None:
    seeded = {telegram_id for _, telegram_id in _expanded_seeds()}
    pattern = re.compile(r"(?<![\w.])(9\d{2}_?\d{3}|1_?00\d_?\d{3})(?!\w)")  # 9xx_xxx and retry ids 1_00x_xxx
    missing: dict[str, list[str]] = collections.defaultdict(list)
    for path in E2E.rglob("*.ts"):
        if "node_modules" in path.parts:
            continue
        for match in pattern.finditer(path.read_text()):
            telegram_id = match.group(1).replace("_", "")
            if telegram_id not in seeded and telegram_id not in UNSEEDED_ON_PURPOSE:
                missing[telegram_id].append(str(path.relative_to(ROOT)))
    assert dict(missing) == {}, f"spec constants refer to unseeded telegram ids: {dict(missing)}"


def test_no_quarantined_specs() -> None:
    offenders = []
    for path in (E2E / "scenarios").rglob("*.spec.ts"):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if "test.fixme" in line or re.search(r"\btest(\.describe)?\.skip\(\s*(true|\"|')", line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == [], f"quarantined/unconditionally skipped E2E specs: {offenders}"
