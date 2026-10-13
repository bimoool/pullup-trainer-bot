"""Control flow of deploy/deploy-staging-guarded-run.sh against stubbed docker/git/curl (no Docker, no network, no database).

What this proves (and what it does not): the ORDER of phases and the safety contract — app/web are never started unless every
check passed, they are stopped again on any later failure, a failure before they were touched changes nothing, and the dispatcher
accepts exactly one literal command. The SQL/data logic is covered by deploy/staging_data_check.sh runs on real rehearsal databases
(docs/STAGING_RC_REHEARSAL.md); the real Docker/Compose behaviour by the sandbox run recorded in docs/STAGING_RC_RUNBOOK.md §3.2.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "deploy" / "deploy-staging-guarded-run.sh"
DISPATCH = ROOT / "deploy" / "deploy-staging-guarded-dispatch.sh"
SHA = "a" * 40
NEW_HEAD = "b5d8e1f3a6c9"
OLD_REV = "c3f7a9e2d5b1"

DOCKER_STUB = r"""#!/usr/bin/env python3
import json, os, sys
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
if args[:2] == ["compose", "version"]:
    out("Docker Compose version v2.40.3-stub"); sys.exit(0)
if args[0] == "compose":
    i = 1
    if args[i] == "-p": i += 2
    sub, rest = args[i], args[i + 1:]
    if sub == "ps":
        svc = rest[-1]
        if svc == "db": out("dbc")
        else: out(svc + "-cid")
        sys.exit(0)
    if sub == "stop": st["running"] = False; save(); sys.exit(0)
    if sub == "build":
        if env.get("FAIL_BUILD") == rest[-1]: sys.stderr.write("build failed\n"); sys.exit(1)
        sys.exit(0)
    if sub == "config": out("pullup-staging-app\npullup-staging-web"); sys.exit(0)
    if sub == "up": st["running"] = True; save(); sys.exit(0)
    if sub == "run":
        cmd = " ".join(rest)
        if "alembic heads" in cmd: out(NEW := "b5d8e1f3a6c9 (head)"); sys.exit(0)
        if "alembic upgrade head" in cmd:
            if env.get("FAIL_MIGRATE"): sys.exit(1)
            st["rev"] = "b5d8e1f3a6c9"; save(); sys.exit(0)
        if "python -c" in cmd: sys.exit(1 if env.get("FAIL_CONV_CHECK") else 0)
        if "repair_plan_convergence" in cmd: out('{"mode": "x", "total_mutations": 0, "users_detail": []}'); sys.exit(0)
        if "backfill_multi_program" in cmd: out("копий без изменений: 1"); sys.exit(0)
    sys.exit(0)
if args[0] == "inspect":
    fmt, cid = args[2], args[3]
    if "com.docker.compose.project" in fmt: out(env.get("DB_PROJECT", "pullup-staging"))
    elif ".State.Running" in fmt: out("true" if (cid == "dbc" or st.get("running")) else "false")
    elif ".State.Restarting" in fmt: out("false")
    elif ".State.Health" in fmt: out("healthy")
    elif ".Image" in fmt: out(("sha256:built-" + cid.split("-")[0]) if st.get("running") and cid != "dbc" else "sha256:old-" + cid.split("-")[0])
    sys.exit(0)
if args[:2] == ["image", "inspect"]:
    out("sha256:built-" + args[-1].rsplit("-", 1)[-1]); sys.exit(0)
if args[0] == "tag": sys.exit(0)
if args[0] == "exec":
    cmdline = " ".join(args)
    if "pg_dump" in cmdline: sys.stdout.write("PGDMP" + "x" * 300); sys.exit(0)
    if "pg_restore -l" in cmdline:
        for n in range(60): out("; toc %d" % n)
        sys.exit(0)
    if "pg_restore" in cmdline: sys.exit(1 if env.get("FAIL_RESTORE") else 0)
    if "dropdb" in cmdline or "createdb" in cmdline: sys.exit(0)
    if "POSTGRES_DB\"" in cmdline and "echo" in cmdline: out(env.get("DB_NAME", "pullup_staging")); sys.exit(0)
    sql = cmdline + "\n" + stdin
    restore = "-d restore_check" in cmdline
    if "alembic_version" in sql: out(env.get("RESTORED_REV", st["rev"]) if restore else st["rev"]); sys.exit(0)
    if "pg_stat_activity" in sql: out(env.get("FOREIGN_CONNS", "0")); sys.exit(0)
    if "n_tup_ins" in sql:
        st["writes"] = st.get("writes", 100) + (1 if env.get("WRITES_CHANGE") else 0); save(); out(str(st["writes"])); sys.exit(0)
    if "from users" in sql: out("9/9/9/9/9" if (restore and env.get("RESTORE_COUNTS_DIFFER")) else "1/2/3/4/5"); sys.exit(0)
    sys.exit(0)
sys.exit(0)
"""

GIT_STUB = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
st_path = Path(os.environ["STUB_STATE"]); log = Path(os.environ["STUB_LOG"])
st = json.loads(st_path.read_text()); args = sys.argv[1:]
log.open("a").write("git " + " ".join(args) + "\n")
if args[:2] == ["rev-parse", "HEAD"]: print(st["head"]); sys.exit(0)
if args[0] == "status": print(os.environ.get("GIT_DIRTY", "")); sys.exit(0)
if args[0] == "fetch": sys.exit(0)
if args[0] == "cat-file": sys.exit(1 if os.environ.get("NO_COMMIT") else 0)
if args[0] == "checkout":
    st["head"] = args[-1]; st_path.write_text(json.dumps(st)); sys.exit(0)
if args[0] == "show":
    path = args[1].split(":", 1)[1]
    if path == "deploy/staging_data_check.sh":
        print("#!/usr/bin/env bash\necho \"CHECK $1\" >> \"$STUB_LOG\"\n[ \"${FAIL_CHECK:-}\" = \"$1\" ] && { echo \"stub check $1 failed\" >&2; exit 1; }\nexit 0")
    elif path == "docs/rehearsal/sql/gen_hash_queries.sql": print("select 1;")
    elif path == "deploy/staging-allowed-diff.txt": print("program_inclusions")
    else: sys.exit(1)
    sys.exit(0)
sys.exit(0)
"""

CURL_STUB = '#!/usr/bin/env bash\necho "curl $*" >> "$STUB_LOG"\n[ "${FAIL_HEALTH:-}" = "1" ] && exit 22\nexit 0\n'


@pytest.fixture()
def sandbox(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", DOCKER_STUB), ("git", GIT_STUB), ("curl", CURL_STUB)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "docker-compose.yml").write_text("services: {}\n")
    (staging / ".env").write_text("BOT_TOKEN=x\n")
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({"rev": OLD_REV, "head": "4298f8b" + "0" * 33, "running": True, "writes": 100})
    )
    log = tmp_path / "log.txt"
    log.write_text("")

    def run(*args: str, **env: str):
        full = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GUARDED_TEST": "1",
            "STAGING_DIR": str(staging),
            "BACKUP_DIR": str(tmp_path / "backups"),
            "HEALTH_URL": "http://127.0.0.1:1/health",
            "STUB_STATE": str(state),
            "STUB_LOG": str(log),
            "TMPDIR": str(tmp_path),
            **env,
        }
        proc = subprocess.run(
            ["bash", str(RUN), *args],
            capture_output=True,
            text=True,
            env=full,
            cwd=str(tmp_path),
            timeout=120,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        lines = log.read_text().splitlines()
        return proc, lines, json.loads(state.read_text())

    def preset(**kw):
        data = json.loads(state.read_text())
        data.update(kw)
        state.write_text(json.dumps(data))

    run.preset = preset  # type: ignore[attr-defined]
    return run


def idx(lines: list[str], needle: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if needle in lines[i]:
            return i
    return -1


def test_full_success_orders_phases_and_starts_only_at_the_end(sandbox):
    proc, log, state = sandbox(SHA, "apply", "yes")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "GUARDED DEPLOY OK" in proc.stdout
    order = [
        idx(log, "docker tag"),
        idx(log, "stop app web"),
        idx(log, "pg_dump"),
        idx(log, f"git checkout --quiet --detach {SHA}"),
        idx(log, "build app"),
        idx(log, "build web"),
        idx(log, "alembic upgrade head"),
        idx(log, "CHECK after-migration"),
        idx(log, "CHECK hold-check"),
        idx(log, "--apply"),
        idx(log, "CHECK after-convergence"),
        idx(log, "up -d --no-build app web"),
        idx(log, "curl"),
    ]
    assert all(i >= 0 for i in order), (order, log)
    assert order == sorted(order), (order, log)
    assert idx(log, "CHECK before") < idx(
        log, f"git checkout --quiet --detach {SHA}"
    )  # снимок «до» снят до смены кода
    assert idx(log, "build app") < idx(log, "build web")  # последовательно
    assert state["running"] is True and state["head"] == SHA and state["rev"] == NEW_HEAD


def test_dry_run_without_start_never_applies_or_starts(sandbox):
    proc, log, state = sandbox(SHA, "dry-run", "no")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "services NOT started" in proc.stdout
    assert (
        idx(log, "--apply") == -1
        and idx(log, "CHECK hold-check") == -1
        and idx(log, "CHECK after-convergence") == -1
    )
    assert idx(log, "up -d") == -1 and state["running"] is False
    assert idx(log, "CHECK same-as-migration") >= 0


@pytest.mark.parametrize(
    "env, stage_must_not_run",
    [
        ({"FAIL_RESTORE": "1"}, "git checkout"),  # backup не восстанавливается
        ({"RESTORE_COUNTS_DIFFER": "1"}, "git checkout"),  # восстановленные счётчики не совпали
        ({"RESTORED_REV": "zzzz"}, "git checkout"),  # версия в восстановленной копии не совпала
        ({"WRITES_CHANGE": "1"}, "pg_dump"),  # БД пишут во время «тишины»
        ({"FOREIGN_CONNS": "2"}, "pg_dump"),  # остались чужие соединения
        ({"FAIL_BUILD": "web"}, "alembic upgrade head"),  # сборка web упала
        ({"FAIL_BUILD": "app"}, "build web"),  # сборка app упала => web не собирается
        ({"FAIL_MIGRATE": "1"}, "CHECK after-migration"),  # миграция упала
        ({"FAIL_CHECK": "after-migration"}, "--apply"),  # проверка данных после миграции
        ({"FAIL_CHECK": "same-as-migration"}, "--apply"),  # dry-run что-то записал
        ({"FAIL_CHECK": "hold-check"}, "--apply"),  # рискованные факультативы
        ({"FAIL_CONV_CHECK": "1"}, "up -d"),  # guard_violations / идемпотентность convergence
        ({"FAIL_CHECK": "after-convergence"}, "up -d"),  # инварианты после convergence
    ],
)
def test_any_failure_after_writers_stopped_leaves_app_and_web_stopped(
    sandbox, env, stage_must_not_run
):
    proc, log, state = sandbox(SHA, "apply", "yes", **env)
    assert proc.returncode != 0, proc.stdout
    assert state["running"] is False, "app/web must be stopped after a failed deploy"
    assert "app/web are STOPPED" in proc.stderr
    assert "rollback images" in proc.stderr and "backup" in proc.stderr
    assert idx(log, stage_must_not_run) == -1, (stage_must_not_run, log)
    assert idx(log, "up -d") == -1, "services must never be started when a check failed"
    assert "GUARDED DEPLOY OK" not in proc.stdout


def test_healthcheck_failure_stops_services_again_after_they_were_started(sandbox):
    proc, log, state = sandbox(SHA, "dry-run", "yes", FAIL_HEALTH="1")
    assert proc.returncode != 0
    assert idx(log, "up -d --no-build app web") >= 0
    assert idx(log, "stop app web", idx(log, "up -d --no-build app web")) > idx(
        log, "up -d --no-build app web"
    )
    assert state["running"] is False


@pytest.mark.parametrize(
    "env",
    [
        {"DB_PROJECT": "prod-project"},
        {"DB_NAME": "pullup"},
        {"GIT_DIRTY": " M x"},
        {"NO_COMMIT": "1"},
    ],
)
def test_preflight_failure_changes_nothing(sandbox, env):
    proc, log, state = sandbox(SHA, "apply", "yes", **env)
    assert proc.returncode != 0
    assert "nothing was changed" in proc.stderr
    assert (
        idx(log, "stop app web") == -1
        and idx(log, "docker tag") == -1
        and idx(log, "pg_dump") == -1
    )
    assert state["running"] is True and state["rev"] == OLD_REV


def test_unknown_alembic_revision_is_refused_before_migrating(sandbox):
    sandbox.preset(rev="unknown999")
    proc, log, state = sandbox(SHA, "apply", "yes", RESTORED_REV="unknown999")
    assert proc.returncode != 0
    assert "unexpected alembic revision" in proc.stderr
    assert (
        idx(log, "alembic upgrade head") == -1
        and idx(log, "up -d") == -1
        and state["running"] is False
    )


def test_already_migrated_database_skips_the_upgrade_but_still_checks(sandbox):
    sandbox.preset(rev=NEW_HEAD)
    proc, log, _state = sandbox(SHA, "dry-run", "no", RESTORED_REV=NEW_HEAD)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "already at head" in proc.stdout
    assert idx(log, "alembic upgrade head") == -1 and idx(log, "CHECK after-migration") >= 0


@pytest.mark.parametrize(
    "args",
    [
        ("short", "apply", "yes"),
        (SHA, "apply-now", "yes"),
        (SHA, "apply", "maybe"),
        (SHA.upper(), "apply", "yes"),
        (SHA, "apply"),
        (SHA, "apply", "yes", "extra"),
    ],
)
def test_bad_arguments_are_rejected_before_anything_runs(sandbox, args):
    proc, log, _state = sandbox(*args)
    assert proc.returncode == 2
    assert log == []


def test_dispatcher_accepts_exactly_one_literal_command():
    text = DISPATCH.read_text()
    pattern = re.search(r"^re='(.+)'$", text, re.MULTILINE).group(1)
    rx = re.compile(pattern)
    ok = f"./deploy-staging-guarded.sh {SHA} apply yes"
    assert rx.fullmatch(ok) and rx.fullmatch(f"./deploy-staging-guarded.sh {SHA} dry-run no")
    for bad in (
        f"./deploy-staging-guarded.sh {SHA} apply",
        f"./deploy-staging-guarded.sh {SHA} apply yes; rm -rf /",
        f"./deploy-staging-guarded.sh {SHA[:39]} apply yes",
        f"./deploy-staging-guarded.sh {SHA.upper()} apply yes",
        f"./deploy-staging.sh {SHA}",
        f"bash -c './deploy-staging-guarded.sh {SHA} apply yes'",
        f" ./deploy-staging-guarded.sh {SHA} apply yes",
        f"./deploy-staging-guarded.sh {SHA} apply yes\n",
        "",
    ):
        assert not rx.fullmatch(bad), bad
    for cmd in (
        f"./deploy-staging-guarded.sh {SHA} apply yes; id",
        f"./deploy-staging-guarded.sh {SHA} apply yes\nid",
        "id",
        "",
    ):  # реальный скрипт отклоняет до любых действий
        proc = subprocess.run(
            ["bash", str(DISPATCH)],
            env={"SSH_ORIGINAL_COMMAND": cmd, "PATH": os.environ["PATH"]},
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1 and "rejected command" in proc.stderr


def test_production_and_existing_staging_deploy_files_are_not_touched():
    out = subprocess.run(
        ["git", "diff", "--name-only", "4298f8b9727f91d4a150431fd0d9e06131944d27", "HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if out.returncode != 0:
        pytest.skip("git history unavailable")
    changed = set(out.stdout.split())
    for forbidden in (
        ".github/workflows/deploy.yml",
        ".github/workflows/deploy-staging.yml",
        "deploy/deploy-run.sh",
    ):
        assert forbidden not in changed
