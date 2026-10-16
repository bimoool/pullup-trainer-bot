"""Control flow of deploy/deploy-production-guarded-run.sh and deploy/rollback-production-guarded.sh against stubbed
docker/git/curl/pgrep (no Docker, no network, no database) — the same approach as test_deploy_staging_guarded.py.

What this proves: argument/token validation happens before anything runs; preflight writes nothing; the ORDER of the apply
phases (build before stop, a verified backup before stop, a verified final backup after stop, migrate -> backfill ->
checks -> start); the fail-safe contract (a failure before the writers were stopped changes nothing visible; after they
were stopped app/web stay stopped and the exact rollback command is printed); R1/R3 rollback order and refusals; no
secret value from .env is ever printed. What it does not prove: the real SQL, pg_dump/pg_restore and Compose behaviour —
that is the rehearsal on a copy of the production dump (docs/PRODUCTION_RUNBOOK.md §4). Linux only (setsid, flock, /proc).
"""

from __future__ import annotations

import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs Linux (setsid, flock, /proc)")

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "deploy" / "deploy-production-guarded-run.sh"
ROLLBACK = ROOT / "deploy" / "rollback-production-guarded.sh"
SHA = "c" * 40
TOKEN = "PRODUCTION-APPLY-" + SHA[:12]
OLD_REV = "e7c2a4f9d1b3"
NEW_HEAD = "b5d8e1f3a6c9"
PREV_SHA = "37b989cf7df9d37ff7430bc24448b35df77b36cc"
SECRETS = ("SECRET-BOT-TOKEN-XYZ", "SECRETPW", "SECRET-SHEET-ID", "SECRET-ROBO")

DOCKER_STUB = r"""#!/usr/bin/env python3
import json, os, re, subprocess, sys, time
from pathlib import Path
state_path = Path(os.environ["STUB_STATE"]); log = Path(os.environ["STUB_LOG"])
st = json.loads(state_path.read_text())
def save(): state_path.write_text(json.dumps(st))
def L(msg): log.open("a").write(msg + "\n")
args = sys.argv[1:]
env = os.environ
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
L("docker " + " ".join(args))
def out(s=""): sys.stdout.write(s + ("\n" if s and not s.endswith("\n") else ""))
joined = " ".join(args)
project = env.get("PROD_PROJECT", "pullup-trainer-bot")
def event(name):
    if env.get("LEGACY_CHANGE_AT") == name: st["legacy_changed"] = True
if env.get("HANG_ON") and env["HANG_ON"] in joined and "--help" not in joined:
    if " run " in f" {joined} ":
        label = next(a.split("=", 1)[1] for a in args if a.startswith("guarded.run="))
        st.setdefault("oneoffs", {})["oneoff-1"] = {"label": label, "running": True}; save()
    L("HANG " + env["HANG_ON"])
    time.sleep(float(env.get("HANG_SECONDS", "60")))
if args[:2] == ["ps", "-aq"]:
    flt = args[args.index("--filter") + 1] if "--filter" in args else ""
    want = flt.split("=", 2)[2] if flt.count("=") >= 2 else None
    for cid, c in st.get("oneoffs", {}).items():
        if c["running"] and (want is None or c["label"] == want): out(cid)
    sys.exit(0)
if args[0] in ("stop", "kill", "rm"):
    for cid in args[1:]:
        if cid in st.get("oneoffs", {}): st["oneoffs"][cid]["running"] = False
    save(); sys.exit(0)
if args[:2] == ["compose", "version"]:
    out("Docker Compose version v2.40.3-stub"); sys.exit(0)
if args[0] == "compose":
    i = 1
    if args[i] == "-p": i += 2
    sub, rest = args[i], args[i + 1:]
    if sub == "run" and "--help" in rest:
        out("  -l, --label stringArray   Add or override a label"); sys.exit(0)
    if sub == "ps":
        if rest == ["-a"]:
            out("NAME  IMAGE  STATUS"); out(project + "-app-1  " + project + "-app  Up"); sys.exit(0)
        svc = rest[-1]
        out("dbc" if svc == "db" else svc + "-cid"); sys.exit(0)
    if sub == "images": out("CONTAINER  REPOSITORY  TAG"); sys.exit(0)
    if sub == "port": out(env.get("STUB_WEB_PORT", "127.0.0.1:8001")); sys.exit(0)
    if sub == "stop":
        for s in rest: st["running"][s] = False
        save(); sys.exit(0)
    if sub == "build":
        if env.get("FAIL_BUILD") == rest[-1]: sys.stderr.write("build failed\n"); sys.exit(1)
        st["latest"][rest[-1]] = "sha256:built-" + rest[-1]; save(); sys.exit(0)
    if sub == "config": out(project + "-app\n" + project + "-web"); sys.exit(0)
    if sub == "up":
        for s in [a for a in rest if a in ("app", "web")]:
            st["running"][s] = True; st["container"][s] = st["latest"][s]
        st["up_calls"] = st.get("up_calls", 0) + 1; save(); sys.exit(0)
    if sub == "run":
        cmd = " ".join(rest)
        if "alembic heads" in cmd: out(env.get("STUB_HEADS", "b5d8e1f3a6c9 (head)")); sys.exit(0)
        if "alembic upgrade head" in cmd:
            if env.get("FAIL_MIGRATE"): sys.exit(1)
            st["rev"] = "b5d8e1f3a6c9"; event("migration"); save(); sys.exit(0)
        if "python -c" in cmd:
            k = rest.index("-c")
            sys.exit(subprocess.run([sys.executable, "-c", rest[k + 1], *rest[k + 2:]], input=stdin, text=True).returncode)
        if "repair_plan_convergence" in cmd:
            bad = [{"user_id": 7, "guard_violations": ["x"]}] if env.get("REPAIR_GUARD") else []
            out(json.dumps({"mode": "dry-run", "users": 3, "total_mutations": 2, "users_detail": bad})); sys.exit(0)
        if "backfill_multi_program" in cmd:
            if "--converge-history" in cmd:
                out("DRY-RUN (ничего не записано)")
                out("RESULT-JSON " + json.dumps({"mode": "dry-run", "users": 3, "mutations": int(env.get("CONVERGE_MUTATIONS", "0")),
                                                 "counts": {"unchanged": 20}, "unresolved": []}, sort_keys=True))
                sys.exit(0)
            n = st.get("backfill_applied", 0)
            if "--dry-run" in cmd:
                if env.get("BACKFILL_DRY_WRITES"): st["v2_version"] += 1; save()
                will, already = (0, 3) if n else (3, 0)
                out("DRY-RUN (ничего не записано)\nОнбордившихся пользователей: %s\n  будет мигрировано: %d\n"
                    "  уже было мигрировано (пропущено): %d\nБудет создано TrainingSession (обычных): 20" % (env.get("STUB_ONBOARDED", "3"), will, already))
                sys.exit(0)
            if env.get("FAIL_BACKFILL"): sys.stderr.write("Traceback: boom\n"); sys.exit(1)
            st["backfill_applied"] = n + 1
            if n == 0 or env.get("BACKFILL_NOT_IDEMPOTENT"): st["v2_version"] += 1
            event("backfill"); save()
            migrated, already = (3, 0) if n == 0 else (0, 3)
            mark = "РАСХОЖДЕНИЕ" if env.get("BACKFILL_MISMATCH") else "OK"
            out("Прогон завершён\nОнбордившихся пользователей: 3\n  мигрировано в этом прогоне: %d\n"
                "  уже было мигрировано (пропущено): %d\nTrainingPlan всего: 3 (ожидается 3) [OK]\n"
                "TrainingSession обычные всего: 20 (ожидается 20) [%s]" % (migrated, already, mark))
            sys.exit(0)
    sys.exit(0)
if args[0] == "inspect":
    fmt, cid = args[2], args[3]
    if "project.working_dir" in fmt: out(env.get("STUB_WORKDIR", env.get("PROD_DIR", "")))
    elif "project.config_files" in fmt: out(env.get("STUB_CONFIG_FILES", env.get("PROD_DIR", "") + "/docker-compose.yml"))
    elif "com.docker.compose.project" in fmt: out(env.get("STUB_DB_PROJECT", project))
    elif ".State.Running" in fmt: out("true" if cid == "dbc" or st["running"].get(cid.split("-")[0]) else "false")
    elif ".State.Restarting" in fmt: out("false")
    elif ".State.Health" in fmt: out("healthy")
    elif ".Config.Image" in fmt: out(project + "-" + cid.split("-")[0])
    elif ".Image" in fmt: out(st["container"][cid.split("-")[0]])
    sys.exit(0)
if args[:2] == ["image", "inspect"]:
    ref = args[-1]
    if ref.startswith("sha256:"):
        if ref in env.get("STUB_MISSING_IMAGES", ""): sys.exit(1)
        out(ref); sys.exit(0)
    out(st["latest"][ref.rsplit("-", 1)[-1]]); sys.exit(0)
if args[0] == "tag":
    src, ref = args[1], args[2]
    st.setdefault("tags", []).append([src, ref])
    if ref in (project + "-app", project + "-web"): st["latest"][ref.rsplit("-", 1)[-1]] = src
    save(); sys.exit(0)
if args[0] == "exec":
    cmdline = " ".join(args)
    if "pg_dump" in cmdline:
        if env.get("FAIL_DUMP"): sys.exit(1)
        st["dump_rev"] = st["rev"]; save(); sys.stdout.write("PGDMP" + "x" * 300); sys.exit(0)
    if "pg_restore -l" in cmdline:
        for n in range(60): out("; toc %d" % n)
        sys.exit(0)
    if "pg_restore" in cmdline:
        if env.get("FAIL_RESTORE"): sys.exit(1)
        if "_rb_" in cmdline and env.get("FAIL_RB_RESTORE"): sys.exit(1)
        sys.exit(0)
    if "dropdb" in cmdline or "createdb" in cmdline: sys.exit(0)
    if 'echo "$POSTGRES_DB"' in cmdline: out(env.get("STUB_DB_NAME", "pullup")); sys.exit(0)
    sql = stdin
    m = re.search(r"-d (\S+) -At", cmdline)
    target = m.group(1) if m else "live"
    if target == '"$POSTGRES_DB"': target = "live"
    if target == "postgres":
        if "ALTER DATABASE" in sql:
            if env.get("FAIL_SWAP"): sys.exit(1)
            st["swapped"] = True; st["rev"] = st.get("dump_rev", st["rev"]); st["v2_version"] = 0; st["legacy_changed"] = False; save(); sys.exit(0)
        if "pg_stat_activity" in sql: out("0"); sys.exit(0)
        sys.exit(0)
    restore = target.endswith("_restore_check")
    rb = "_rb_" in target
    if "alembic_version" in sql:
        if restore: out(env.get("RESTORED_REV", st["rev"]))
        elif rb: out(st.get("dump_rev", "none"))
        else: out(st["rev"])
        sys.exit(0)
    if "pg_stat_activity" in sql: out(env.get("FOREIGN_CONNS", "0")); sys.exit(0)
    if "n_tup_ins" in sql:
        st["writes"] = st.get("writes", 100) + (1 if env.get("WRITES_CHANGE") else 0); save(); out(str(st["writes"])); sys.exit(0)
    if "q:legacy-counts" in sql:
        out("99/99/99/99" if ((restore or rb) and env.get("RESTORE_COUNTS_DIFFER")) else "10/20/5/3"); sys.exit(0)
    if "pg_size_pretty" in sql: out("12 MB"); sys.exit(0)
    if "information_schema.tables" in sql:
        tables = ["users", "workouts", "elective_workouts", "subscriptions"]
        if st["rev"] == "b5d8e1f3a6c9": tables += ["training_plans", "training_sessions", "program_inclusions"]
        for t in tables: out("select '%s' as tbl, count(*) as n, md5('x') as h from %s;" % (t, t))
        sys.exit(0)
    if " as tbl," in sql:
        for t in re.findall(r"select '(\w+)' as tbl,", sql):
            if t in ("users", "workouts", "elective_workouts", "subscriptions"):
                h = "L-changed" if (st.get("legacy_changed") and t == "users") else "L"
            else:
                h = "N%d" % st["v2_version"]
            out("%s|5|%s" % (t, h))
        sys.exit(0)
    if "inv:noplan" in sql: out(env.get("INV_NOPLAN", "0")); sys.exit(0)
    if "inv:inclusion" in sql or "inv:dups" in sql: out("0"); sys.exit(0)
    if "inv:plans" in sql: out(env.get("INV_PLANS", "3")); sys.exit(0)
    if "q:origins" in sql: out("legacy_backfill=20"); sys.exit(0)
    if "||'/'||" in sql: out("10/3/20/5/3"); sys.exit(0)
    if "onboarding_completed_at is not null" in sql: out("3"); sys.exit(0)
    sys.exit(0)
sys.exit(0)
"""

GIT_STUB = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
st_path = Path(os.environ["STUB_STATE"]); log = Path(os.environ["STUB_LOG"])
st = json.loads(st_path.read_text()); args = sys.argv[1:]
if args[:1] == ["-C"]: args = args[2:]
log.open("a").write("git " + " ".join(args) + "\n")
if args[:2] == ["rev-parse", "HEAD"]: print(st["head"]); sys.exit(0)
if args[:2] == ["rev-parse", "--verify"]:
    print(os.environ.get("GIT_RESOLVES_TO") or args[-1].split("^")[0]); sys.exit(0)
if args[0] == "status": print(os.environ.get("GIT_DIRTY", "")); sys.exit(0)
if args[0] == "fetch": sys.exit(0)
if args[0] == "merge-base": sys.exit(1 if os.environ.get("NOT_ANCESTOR") else 0)
if args[0] == "cat-file":
    obj = args[-1]
    if os.environ.get("NO_COMMIT") and obj.endswith("^{commit}") and not obj.startswith("37b989c"): sys.exit(1)
    sys.exit(0)
if args[0] == "checkout":
    st["head"] = args[-1]; st_path.write_text(json.dumps(st)); sys.exit(0)
if args[0] == "show": print("-- generator: select ... from information_schema.tables ..."); sys.exit(0)
sys.exit(0)
"""

SHA256_STUB = """#!/usr/bin/env bash
if [ "${BAD_CHECKSUM:-}" = "1" ]; then
  for a in "$@"; do [ "$a" = "-c" ] && { echo "sha256sum -c: FAILED" >&2; exit 1; }; done
fi
exec /usr/bin/sha256sum "$@"
"""

CURL_STUB = '#!/usr/bin/env bash\necho "curl $*" >> "$STUB_LOG"\n[ "${FAIL_HEALTH:-}" = "1" ] && exit 22\nexit 0\n'
PGREP_STUB = '#!/usr/bin/env bash\necho "pgrep $*" >> "$STUB_LOG"\n[ -n "${PGREP_MATCH:-}" ] && [[ "$*" == *"$PGREP_MATCH"* ]] && exit 0\nexit 1\n'

ENV_FILE = (
    "BOT_TOKEN=SECRET-BOT-TOKEN-XYZ\n"
    "DATABASE_URL=postgresql+asyncpg://pullup:SECRETPW@db:5432/pullup\n"
    "MINI_APP_URL=https://app.bimoool.com\n"
    "ROBOKASSA_PASSWORD_1=SECRET-ROBO\n"
    "GOOGLE_SHEETS_SPREADSHEET_ID=SECRET-SHEET-ID\n"
    "GOOGLE_SHEETS_CREDENTIALS_PATH=/app/secrets/SECRET-SHEET-ID.json\n"
)


def initial_state() -> dict:
    return {
        "rev": OLD_REV,
        "head": PREV_SHA,
        "running": {"app": True, "web": True},
        "latest": {"app": "sha256:old-app", "web": "sha256:old-web"},
        "container": {"app": "sha256:old-app", "web": "sha256:old-web"},
        "writes": 100,
        "v2_version": 0,
    }


@pytest.fixture()
def sandbox(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (
        ("docker", DOCKER_STUB),
        ("git", GIT_STUB),
        ("curl", CURL_STUB),
        ("pgrep", PGREP_STUB),
        ("sha256sum", SHA256_STUB),
    ):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    prod = tmp_path / "prod"
    prod.mkdir()
    (prod / "docker-compose.yml").write_text("services: {}\n")
    (prod / ".env").write_text(ENV_FILE)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    state = tmp_path / "state.json"
    state.write_text(json.dumps(initial_state()))
    log = tmp_path / "log.txt"
    log.write_text("")
    base_env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PROD_DIR": str(prod),
        "PROD_BACKUP_DIR": str(tmp_path / "backups"),
        "PROD_QUIESCE_SECONDS": "0",
        "PROD_HEALTH_TIMEOUT": "4",
        "PROD_MIN_DISK_MB": "1",
        "PROD_MIN_MEM_MB": "0",
        "STUB_STATE": str(state),
        "STUB_LOG": str(log),
        "TMPDIR": str(tmpdir),
    }

    def run(*args: str, script: Path = RUN, **env: str):
        proc = subprocess.run(
            ["bash", str(script), *args],
            capture_output=True,
            text=True,
            env={**base_env, **env},
            cwd=str(tmp_path),
            timeout=120,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        return proc, log.read_text().splitlines(), json.loads(state.read_text())

    def preset(**kw):
        data = json.loads(state.read_text())
        data.update(kw)
        state.write_text(json.dumps(data))

    run.preset = preset  # type: ignore[attr-defined]
    run.env = base_env  # type: ignore[attr-defined]
    run.root = tmp_path  # type: ignore[attr-defined]
    run.log = log  # type: ignore[attr-defined]
    run.state = state  # type: ignore[attr-defined]
    run.prod = prod  # type: ignore[attr-defined]
    return run


def idx(lines: list[str], needle: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if needle in lines[i]:
            return i
    return -1


def idx_end(lines: list[str], suffix: str) -> int:
    return next((i for i, line in enumerate(lines) if line.endswith(suffix)), -1)


def manifest_of(sandbox) -> Path:
    return next((sandbox.root / "backups").glob("prod-pre-*.manifest"))


# --- arguments and tokens -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        (),
        (SHA,),
        ("short", "preflight"),
        (SHA.upper(), "preflight"),
        (SHA, "deploy"),
        (SHA, "apply"),  # без токена
        (SHA, "apply", "yes"),
        (SHA, "apply", "PRODUCTION-APPLY-" + "d" * 12),  # токен другого SHA
        (SHA, "apply", TOKEN.lower()),
        (SHA, "preflight", TOKEN),  # токен только с apply
        (SHA, "rehearse-check", TOKEN),
        (SHA, "apply", TOKEN, "extra"),
    ],
)
def test_bad_arguments_are_rejected_before_anything_runs(sandbox, args):
    proc, log, state = sandbox(*args)
    assert proc.returncode == 2, proc.stderr
    assert log == []
    assert state == initial_state()


@pytest.mark.parametrize(
    "env",
    [
        {"PROD_DIR": "relative/dir"},
        {"PROD_PROJECT": "Bad Project"},
        {"PROD_DB_NAME": "pullup; drop table users"},
        {"PROD_EXPECTED_FROM_REV": "zz"},
        {"PROD_HEALTH_URL": "http://evil.example/health"},
        {"PROD_KEEP_BACKUPS": "0"},
        {"PROD_REQUIRED_ANCESTORS": "628144f"},
    ],
)
def test_unsafe_parameters_are_rejected_before_anything_runs(sandbox, env):
    proc, log, _state = sandbox(SHA, "apply", TOKEN, **env)
    assert proc.returncode == 2 and log == [], proc.stderr


# --- preflight -------------------------------------------------------------------------------------------------------


def snapshot_files(root: Path) -> set[str]:
    skip = {"log.txt", "state.json"}
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.name not in skip}


def test_preflight_is_read_only_and_reports_the_state(sandbox):
    before = snapshot_files(sandbox.root)
    proc, log, state = sandbox(SHA, "preflight")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = proc.stdout
    assert "PREFLIGHT OK (read-only)" in out
    for fact in (f"prod HEAD={PREV_SHA}", f"alembic current={OLD_REV}", "size=12 MB", "free disk", "memory available",
                 "last backups in", "containers of pullup-trainer-bot", "images of pullup-trainer-bot",
                 "health url: http://127.0.0.1:8001/health"):
        assert fact in out, fact
    assert "required env keys (names only): BOT_TOKEN DATABASE_URL MINI_APP_URL — missing/empty: none" in out
    assert "Google Sheets export env keys set (names only): GOOGLE_SHEETS_CREDENTIALS_PATH GOOGLE_SHEETS_SPREADSHEET_ID" in out
    for mutating in ("git fetch", "git checkout", "docker tag", "compose -p pullup-trainer-bot stop", "build", "pg_dump",
                     "run --rm", "up -d", "createdb", "dropdb"):
        assert idx(log, mutating) == -1, (mutating, log)
    assert snapshot_files(sandbox.root) == before, "preflight must not create files (no backups dir, no temp dir, no lock)"
    assert state == initial_state()


@pytest.mark.parametrize(
    ("env", "reason"),
    [
        ({"STUB_DB_PROJECT": "pullup-staging"}, "not in project"),
        ({"STUB_WORKDIR": "/home/deploy/pullup-trainer-bot-staging"}, "was created from"),
        ({"STUB_CONFIG_FILES": "/x/docker-compose.yml,/x/docker-compose.override.yml"}, "config files"),
        ({"STUB_DB_NAME": "pullup_staging"}, "POSTGRES_DB of the db container"),
        ({"STUB_DB_NAME": "pullup_staging", "PROD_DB_NAME": "pullup_staging"}, "looks like staging/test"),
        ({"GIT_DIRTY": " M app/main.py"}, "not clean"),
        ({"NO_COMMIT": "1"}, "is not available after fetch"),
        ({"GIT_RESOLVES_TO": "d" * 40}, "different commit"),
        ({"NOT_ANCESTOR": "1"}, "does not contain required commit 628144fa5457"),
        ({"PROD_MIN_DISK_MB": "999999"}, "free disk"),
        ({"STUB_WEB_PORT": ""}, "cannot determine the web port"),
        ({"PGREP_MATCH": "deploy-run"}, "deploy-run.sh) is running"),
        ({"PGREP_MATCH": "deploy-staging"}, "staging deploy is running"),
        ({"PROD_EXPECTED_FROM_REV": "aaaaaaaaaaaa"}, "unexpected alembic revision"),
    ],
)
def test_preflight_gates_refuse_before_anything_is_changed(sandbox, env, reason):
    proc, log, state = sandbox(SHA, "apply", TOKEN, **env)
    assert proc.returncode == 1, proc.stdout
    assert reason in proc.stderr, proc.stderr
    assert "failed before anything was changed" in proc.stderr
    for mutating in ("docker tag", "git checkout", "build", "pg_dump", "stop app web"):
        assert idx(log, mutating) == -1, (mutating, log)
    assert state == initial_state()


def test_missing_env_key_and_wrong_mini_app_url_are_refused(sandbox):
    (sandbox.prod / ".env").write_text(ENV_FILE.replace("BOT_TOKEN=SECRET-BOT-TOKEN-XYZ\n", "BOT_TOKEN=\n"))
    proc, _log, _state = sandbox(SHA, "preflight")
    assert proc.returncode == 1 and "required env keys missing or empty: BOT_TOKEN" in proc.stderr
    (sandbox.prod / ".env").write_text(ENV_FILE.replace("https://app.bimoool.com", "https://staging.app.bimoool.com"))
    proc, _log, _state = sandbox(SHA, "preflight")
    assert proc.returncode == 1 and "MINI_APP_URL in .env is not exactly https://app.bimoool.com" in proc.stderr
    (sandbox.prod / ".env").write_text(ENV_FILE.replace("/pullup\n", "/otherdb\n"))
    proc, _log, _state = sandbox(SHA, "preflight")
    assert proc.returncode == 1 and "database name in DATABASE_URL ('otherdb')" in proc.stderr


# --- apply: order ---------------------------------------------------------------------------------------------------


def test_apply_runs_phases_in_the_safe_order_and_starts_only_at_the_end(sandbox):
    proc, log, state = sandbox(SHA, "apply", TOKEN)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "PRODUCTION GUARDED DEPLOY OK" in proc.stdout
    stop = idx(log, "compose -p pullup-trainer-bot stop app web")
    dumps = [i for i, line in enumerate(log) if "pg_dump" in line]
    order = [
        idx(log, "git fetch"),
        idx(log, "docker tag sha256:old-app local/prod-app:pre-ccccccc-"),
        idx(log, f"git checkout --quiet --detach {SHA}"),
        idx(log, "build app"),
        idx(log, "build web"),
        dumps[0],  # бэкап ДО остановки
        idx(log, "pullup_restore_check --no-owner"),  # ... и его пробное восстановление — тоже до остановки
        stop,
        dumps[1],  # финальный бэкап при остановленных писателях
        idx(log, "alembic upgrade head"),
        idx(log, "backfill_multi_program.py --dry-run"),
        idx_end(log, "app python scripts/backfill_multi_program.py"),  # apply
        idx(log, "--converge-history"),
        idx(log, "repair_plan_convergence.py --all"),
        idx(log, "up -d --no-build app web"),
        idx(log, "curl"),
    ]
    assert len(dumps) == 2, dumps
    assert all(i >= 0 for i in order), (order, log)
    assert order == sorted(order), (order, log)
    assert idx(log, "build app") < stop and idx(log, "build web") < stop  # сборка до простоя
    assert len([line for line in log if line.endswith("app python scripts/backfill_multi_program.py")]) == 2  # apply + повтор
    dry = [i for i, line in enumerate(log) if line.endswith("backfill_multi_program.py --dry-run")]
    assert len(dry) == 2 and dry[1] > idx_end(log, "app python scripts/backfill_multi_program.py")  # контрольный dry-run после apply
    assert not any("--apply" in line for line in log)  # сведение никогда не применяется ко всем
    assert idx(log, "post-deploy-cleanup") == -1
    assert state["running"] == {"app": True, "web": True} and state["head"] == SHA and state["rev"] == NEW_HEAD
    assert state["container"] == {"app": "sha256:built-app", "web": "sha256:built-web"}
    assert "R3: " in proc.stdout and "ROLLBACK-R3-prod-ccccccc-" in proc.stdout  # блок состояния для отката


def test_manifest_records_rollback_facts_and_progress_markers(sandbox):
    proc, _log, _state = sandbox(SHA, "apply", TOKEN)
    assert proc.returncode == 0, proc.stderr
    text = manifest_of(sandbox).read_text()
    for line in (f"previous_sha={PREV_SHA}", f"previous_alembic={OLD_REV}", "project=pullup-trainer-bot",
                 f"dir={sandbox.prod}", "db_name=pullup", "health_url=http://127.0.0.1:8001/health",
                 "app_image_id=sha256:old-app", "web_image_id=sha256:old-web", "app_compose_image=pullup-trainer-bot-app",
                 "app_saved_tag=local/prod-app:pre-ccccccc-", "legacy_counts=10/20/5/3", "backup_sha256=",
                 "migration_started_at=", "backfill_started_at=", "backfill_done_at=", "deploy_ok_at="):
        assert line in text, line
    dump = next((sandbox.root / "backups").glob("prod-pre-*.dump"))
    assert f"backup={dump}" in text
    assert (sandbox.root / "backups" / (dump.name + ".sha256")).exists()
    assert list((sandbox.root / "backups").glob("prod-prestop-*.dump"))
    reports = sorted(p.name for p in (sandbox.root / "backups").glob("prod-backfill-*/*"))
    assert reports == ["1-dry-run.txt", "2-apply.txt", "3-reapply.txt", "3b-post-apply-dry-run.txt", "4-converge-history-dry-run.txt", "5-repair-plan-dry-run.json"]


def test_no_secret_value_is_ever_printed_or_written(sandbox):
    proc, log, _state = sandbox(SHA, "apply", TOKEN)
    assert proc.returncode == 0, proc.stderr
    written = "\n".join(p.read_text(errors="ignore") for p in (sandbox.root / "backups").rglob("*") if p.is_file())
    for secret in SECRETS:
        assert secret not in proc.stdout + proc.stderr, secret
        assert secret not in "\n".join(log), secret
        assert secret not in written, secret
    proc, _log, _state = sandbox(SHA, "preflight")
    for secret in SECRETS:
        assert secret not in proc.stdout + proc.stderr, secret


def test_old_backups_are_rotated_only_after_success(sandbox):
    backups = sandbox.root / "backups"
    backups.mkdir()
    for n in range(5):
        f = backups / f"prod-pre-aaaaaaa-2026010{n}T000000Z.dump"
        f.write_text("old")
        os.utime(f, (1_700_000_000 + n, 1_700_000_000 + n))
    proc, _log, _state = sandbox(SHA, "apply", TOKEN, PROD_KEEP_BACKUPS="2")
    assert proc.returncode == 0, proc.stderr
    left = sorted(p.name for p in backups.glob("prod-pre-*.dump"))
    assert len(left) == 3 and "prod-pre-aaaaaaa-20260104T000000Z.dump" in left and "prod-pre-aaaaaaa-20260103T000000Z.dump" in left


# --- fail-safe ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "must_not_run"),
    [
        ({"FAIL_BUILD": "app"}, "build web"),
        ({"FAIL_BUILD": "web"}, "pg_dump"),
        ({"FAIL_DUMP": "1"}, "stop app web"),  # бэкап до остановки не удался => простоя нет
        ({"FAIL_RESTORE": "1"}, "stop app web"),
        ({"BAD_CHECKSUM": "1"}, "stop app web"),
        ({"RESTORED_REV": "ffffffffffff"}, "stop app web"),
    ],
)
def test_failure_before_writers_stopped_keeps_production_running_on_previous_code(sandbox, env, must_not_run):
    proc, log, state = sandbox(SHA, "apply", TOKEN, **env)
    assert proc.returncode == 1, proc.stdout
    assert "failed before app/web were stopped" in proc.stderr
    assert idx(log, must_not_run) == -1, (must_not_run, log)
    assert idx(log, "stop app web") == -1 and idx(log, "up -d") == -1
    assert state["running"] == {"app": True, "web": True}
    assert state["head"] == PREV_SHA, "checkout must be returned to the previous commit"
    assert state["latest"] == {"app": "sha256:old-app", "web": "sha256:old-web"}, ":latest must point to the previous images"
    assert state["rev"] == OLD_REV


@pytest.mark.parametrize(
    ("env", "must_not_run", "rollback"),
    [
        ({"FOREIGN_CONNS": "2"}, "alembic upgrade head", "R1"),
        ({"WRITES_CHANGE": "1"}, "alembic upgrade head", "R1"),
        ({"RESTORE_COUNTS_DIFFER": "1"}, "alembic upgrade head", "R1"),
        ({"STUB_HEADS": "aaaaaaaaaaaa (head)\nbbbbbbbbbbbb (head)"}, "alembic upgrade head", "R1"),
        ({"FAIL_MIGRATE": "1"}, "app python scripts/backfill_multi_program", "R1"),
        ({"LEGACY_CHANGE_AT": "migration"}, "app python scripts/backfill_multi_program", "R3"),
        ({"STUB_ONBOARDED": "4"}, "Прогон", "R3"),  # dry-run видит не тех пользователей
        ({"BACKFILL_DRY_WRITES": "1"}, "Прогон", "R3"),  # dry-run что-то записал
        ({"FAIL_BACKFILL": "1"}, "--converge-history", "R3"),
        ({"BACKFILL_MISMATCH": "1"}, "--converge-history", "R3"),
        ({"BACKFILL_NOT_IDEMPOTENT": "1"}, "--converge-history", "R3"),
        ({"LEGACY_CHANGE_AT": "backfill"}, "--converge-history", "R3"),
        ({"CONVERGE_MUTATIONS": "4"}, "app python scripts/repair_plan_convergence", "R3"),
        ({"REPAIR_GUARD": "1"}, "up -d", "R3"),
        ({"INV_NOPLAN": "1"}, "up -d", "R3"),
        ({"INV_PLANS": "2"}, "up -d", "R3"),
    ],
)
def test_failure_after_writers_stopped_leaves_services_stopped_and_prints_rollback(sandbox, env, must_not_run, rollback):
    proc, log, state = sandbox(SHA, "apply", TOKEN, **env)
    assert proc.returncode == 1, proc.stdout
    assert state["running"] == {"app": False, "web": False}
    assert "app/web are STOPPED" in proc.stderr
    assert idx(log, "up -d") == -1, "services must never be started when a check failed"
    if must_not_run != "Прогон":
        assert idx(log, must_not_run) == -1, (must_not_run, log)
    else:
        assert idx_end(log, "app python scripts/backfill_multi_program.py") == -1, log
    assert f"rollback-production-guarded.sh {rollback} " in proc.stderr, proc.stderr
    assert f"apply ROLLBACK-{rollback}-prod-ccccccc-" in proc.stderr
    assert "PRODUCTION GUARDED DEPLOY OK" not in proc.stdout
    assert list((sandbox.root / "backups").glob("prod-guarded-*.FAILED.txt"))


def test_healthcheck_failure_stops_services_again_and_points_to_r3(sandbox):
    proc, log, state = sandbox(SHA, "apply", TOKEN, FAIL_HEALTH="1")
    assert proc.returncode == 1
    up = idx(log, "up -d --no-build app web")
    assert up >= 0 and idx(log, "stop app web", up + 1) > up
    assert state["running"] == {"app": False, "web": False}
    assert "healthcheck" in proc.stderr and "rollback-production-guarded.sh R3" in proc.stderr


@pytest.mark.parametrize(("sig", "num"), [(signal.SIGTERM, 15), (signal.SIGHUP, 1), (signal.SIGINT, 2)])
@pytest.mark.parametrize("hang_on", ["alembic upgrade head", "backfill_multi_program.py --dry-run"])
def test_signal_during_downtime_stops_services_and_oneoffs(sandbox, sig, num, hang_on):
    proc = subprocess.Popen(
        ["bash", str(RUN), SHA, "apply", TOKEN],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(sandbox.root),
        env={**sandbox.env, "HANG_ON": hang_on}, stdin=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 60
    while "HANG " + hang_on not in sandbox.log.read_text():
        assert time.monotonic() < deadline, sandbox.log.read_text()
        time.sleep(0.1)
    started = time.monotonic()
    proc.send_signal(sig)
    _out, err = proc.communicate(timeout=30)
    state = json.loads(sandbox.state.read_text())
    assert proc.returncode == 128 + num, err
    assert time.monotonic() - started < 10
    assert state["running"] == {"app": False, "web": False}
    assert not any(c["running"] for c in state.get("oneoffs", {}).values())
    assert f"signal SIG{sig.name[3:]}" in err and "rollback-production-guarded.sh" in err
    assert idx(sandbox.log.read_text().splitlines(), "up -d") == -1


def test_leftover_oneoffs_of_a_killed_run_block_the_next_run(sandbox):
    sandbox.preset(oneoffs={"oneoff-9": {"label": "prod-old", "running": True}})
    proc, log, state = sandbox(SHA, "apply", TOKEN)
    assert proc.returncode == 1 and "one-off containers of an earlier guarded run" in proc.stderr
    assert idx(log, "stop app web") == -1 and state["running"] == {"app": True, "web": True}


def test_second_concurrent_run_is_refused_by_the_lock(sandbox):
    proc1 = subprocess.Popen(
        ["bash", str(RUN), SHA, "apply", TOKEN], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=str(sandbox.root), env={**sandbox.env, "HANG_ON": "build app", "HANG_SECONDS": "8"}, stdin=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 60
    while "HANG build app" not in sandbox.log.read_text():
        assert time.monotonic() < deadline
        time.sleep(0.1)
    proc2, _log, _state = sandbox(SHA, "apply", TOKEN)
    proc1.send_signal(signal.SIGTERM)
    proc1.communicate(timeout=30)
    assert proc2.returncode == 1 and "another production guarded run holds" in proc2.stderr


# --- rehearse-check -------------------------------------------------------------------------------------------------


def rehearsal_env(sandbox) -> dict[str, str]:
    (sandbox.prod / ".env").write_text(ENV_FILE.replace("https://app.bimoool.com", "https://rehearsal.invalid"))
    return {"PROD_PROJECT": "pullup-rehearsal"}


def test_rehearse_check_runs_the_full_path_but_never_starts_the_bot(sandbox):
    proc, log, state = sandbox(SHA, "rehearse-check", **rehearsal_env(sandbox))
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "REHEARSAL OK" in proc.stdout
    assert idx(log, "alembic upgrade head") >= 0 and idx_end(log, "app python scripts/backfill_multi_program.py") >= 0
    assert idx(log, "up -d --no-build web") >= 0 and idx(log, "up -d --no-build app") == -1
    assert state["running"] == {"app": False, "web": False}, "rehearsal never leaves services running"
    assert "rollback-production-guarded.sh R3" in proc.stdout


@pytest.mark.parametrize("prod_like", ["project", "url"])
def test_rehearse_check_refuses_anything_that_looks_like_production(sandbox, prod_like):
    env = rehearsal_env(sandbox)
    if prod_like == "project":
        env = {}  # проект по умолчанию = прод
    else:
        (sandbox.prod / ".env").write_text(ENV_FILE)  # MINI_APP_URL прода
    proc, log, state = sandbox(SHA, "rehearse-check", **env)
    assert proc.returncode == 1
    assert "rehearse-check" in proc.stderr and "failed before anything was changed" in proc.stderr
    assert idx(log, "docker tag") == -1 and state == initial_state()


# --- rollback ---------------------------------------------------------------------------------------------------------


def failed_deploy(sandbox, **env) -> Path:
    proc, _log, state = sandbox(SHA, "apply", TOKEN, **env)
    assert proc.returncode == 1 and state["running"] == {"app": False, "web": False}
    return manifest_of(sandbox)


def run_id(manifest: Path) -> str:
    return re.search(r"^run_id=(.+)$", manifest.read_text(), re.MULTILINE).group(1)


def test_rollback_arguments_and_tokens_are_validated_before_anything_runs(sandbox):
    manifest = failed_deploy(sandbox, FAIL_MIGRATE="1")
    rid = run_id(manifest)
    open(sandbox.log, "w").close()
    for args in (
        ("R2", str(manifest), "check"),
        ("R1", "relative.manifest", "check"),
        ("R1", str(manifest), "apply"),
        ("R1", str(manifest), "apply", f"ROLLBACK-R3-{rid}"),  # токен другого вида отката
        ("R3", str(manifest), "apply", "ROLLBACK-R3-prod-other"),
        ("R1", str(manifest), "check", f"ROLLBACK-R1-{rid}"),
        ("R1", str(sandbox.root / "missing.manifest"), "check"),
    ):
        proc, log, _state = sandbox(*args, script=ROLLBACK)
        assert proc.returncode == 2, (args, proc.stderr)
        assert log == [], args


def test_r1_after_failed_migration_restores_previous_images_without_touching_the_db(sandbox):
    manifest = failed_deploy(sandbox, FAIL_MIGRATE="1")
    rid = run_id(manifest)
    open(sandbox.log, "w").close()
    proc, log, state = sandbox("R1", str(manifest), "check", script=ROLLBACK)
    assert proc.returncode == 0, proc.stderr
    assert "CHECK OK (read-only)" in proc.stdout and "data loss: none" in proc.stdout
    assert idx(log, "stop") == -1 and idx(log, "docker tag") == -1 and idx(log, "up -d") == -1
    proc, log, state = sandbox("R1", str(manifest), "apply", f"ROLLBACK-R1-{rid}", script=ROLLBACK)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    order = [
        idx(log, "stop app web"),
        idx(log, f"git checkout --quiet --detach {PREV_SHA}"),
        idx(log, "docker tag sha256:old-app pullup-trainer-bot-app"),
        idx(log, "docker tag sha256:old-web pullup-trainer-bot-web"),
        idx(log, "up -d --no-build app web"),
        idx(log, "curl"),
    ]
    assert all(i >= 0 for i in order) and order == sorted(order), (order, log)
    assert idx(log, "pg_restore") == -1 and idx(log, "ALTER DATABASE") == -1
    assert state["container"] == {"app": "sha256:old-app", "web": "sha256:old-web"}
    assert state["running"] == {"app": True, "web": True} and state["head"] == PREV_SHA and state["rev"] == OLD_REV
    assert "ROLLBACK R1 OK" in proc.stdout


@pytest.mark.parametrize("failure", [{"FAIL_BACKFILL": "1"}, {"FAIL_HEALTH": "1"}])
def test_r1_is_refused_once_the_schema_or_data_changed(sandbox, failure):
    manifest = failed_deploy(sandbox, **failure)
    open(sandbox.log, "w").close()
    proc, log, state = sandbox("R1", str(manifest), "apply", f"ROLLBACK-R1-{run_id(manifest)}", script=ROLLBACK)
    assert proc.returncode == 1
    assert "R1 is not valid" in proc.stderr and "use R3" in proc.stderr
    assert "nothing was stopped or changed" in proc.stderr
    assert idx(log, "up -d") == -1 and idx(log, "docker tag") == -1


def test_r3_restores_the_dump_into_a_new_db_swaps_and_starts_previous_images(sandbox):
    manifest = failed_deploy(sandbox, FAIL_HEALTH="1")
    rid = run_id(manifest)
    open(sandbox.log, "w").close()
    proc, log, _state = sandbox("R3", str(manifest), "check", script=ROLLBACK)
    assert proc.returncode == 0, proc.stderr
    assert "DATA LOSS WINDOW" in proc.stdout and "_failed_" in proc.stdout
    assert idx(log, "stop") == -1 and idx(log, "createdb") == -1 and idx(log, "ALTER DATABASE") == -1
    open(sandbox.log, "w").close()
    proc, log, state = sandbox("R3", str(manifest), "apply", f"ROLLBACK-R3-{rid}", script=ROLLBACK)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    order = [
        idx(log, "stop app web"),
        idx(log, "createdb -U \"$POSTGRES_USER\" pullup_rb_"),
        idx(log, "-d pullup_rb_"),  # восстановление в НОВУЮ БД
        idx(log, "-d postgres", idx(log, "-d pullup_rb_")),  # затем атомарная перестановка имён
        idx(log, f"git checkout --quiet --detach {PREV_SHA}"),
        idx(log, "docker tag sha256:old-app pullup-trainer-bot-app"),
        idx(log, "up -d --no-build app web"),
        idx(log, "curl"),
    ]
    assert all(i >= 0 for i in order) and order == sorted(order), (order, log)
    assert not any("dropdb" in line for line in log), "R3 never drops the live database (it is renamed and kept)"
    assert state["swapped"] is True and state["rev"] == OLD_REV
    assert state["container"] == {"app": "sha256:old-app", "web": "sha256:old-web"}
    assert state["running"] == {"app": True, "web": True}
    assert "DATA LOSS WINDOW" in proc.stdout and "ROLLBACK R3 OK" in proc.stdout
    assert "rollback_R3_done_at=" in manifest.read_text()


@pytest.mark.parametrize(
    ("env", "reason", "swap_expected"),
    [
        ({"BAD_CHECKSUM": "1"}, "checksum", False),
        ({"STUB_MISSING_IMAGES": "sha256:old-app"}, "no longer exists", False),
        ({"FAIL_RB_RESTORE": "1"}, "pg_restore into", False),
        ({"RESTORE_COUNTS_DIFFER": "1"}, "restored legacy counts differ", False),
        ({"FAIL_SWAP": "1"}, "database swap failed", False),
        ({"FAIL_HEALTH": "1"}, "healthcheck", True),
    ],
)
def test_r3_failures_keep_services_stopped(sandbox, env, reason, swap_expected):
    manifest = failed_deploy(sandbox, FAIL_BACKFILL="1")
    open(sandbox.log, "w").close()
    proc, log, state = sandbox("R3", str(manifest), "apply", f"ROLLBACK-R3-{run_id(manifest)}", script=ROLLBACK, **env)
    assert proc.returncode == 1, proc.stdout
    assert reason in proc.stderr, proc.stderr
    assert state["running"] == {"app": False, "web": False}
    assert bool(state.get("swapped")) is swap_expected
    if not swap_expected:
        assert idx(log, "up -d") == -1


def test_rollback_refuses_a_manifest_from_another_project(sandbox):
    manifest = failed_deploy(sandbox, FAIL_MIGRATE="1")
    open(sandbox.log, "w").close()
    proc, log, _state = sandbox("R1", str(manifest), "check", script=ROLLBACK, STUB_DB_PROJECT="pullup-staging")
    assert proc.returncode == 1 and "not in project" in proc.stderr
    assert idx(log, "stop") == -1


def test_production_scripts_do_not_touch_the_staging_or_plain_deploy_files():
    text = RUN.read_text() + ROLLBACK.read_text()
    assert "deploy-staging-guarded-run.sh" not in text.replace("deploy-staging(-guarded)?-run", "")
    assert "post-deploy-cleanup.sh" not in RUN.read_text().split("set -euo pipefail", 1)[1]
    assert "staging_data_check.sh" not in text
