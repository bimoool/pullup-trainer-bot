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
import signal
import stat
import subprocess
import time
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
joined = " ".join(args)
if env.get("HANG_ON") and env["HANG_ON"] in joined and "--help" not in joined:
    # зависание в этой точке; если это `compose run`, его one-off контейнер «работает», пока его не остановят
    if " run " in f" {joined} ":
        label = next(a.split("=", 1)[1] for a in args if a.startswith("guarded.run="))
        st.setdefault("oneoffs", {})["oneoff-1"] = {"label": label, "running": True}; save()
    L("HANG " + env["HANG_ON"])
    if env.get("LATE_CREATE") and " run " in f" {joined} ":
        # как настоящий compose run: на TERM клиент ещё успевает создать one-off контейнер и только потом выходит
        import signal as _signal, time as _t
        def _late(*_):
            _t.sleep(1.0)
            st2 = json.loads(state_path.read_text())
            st2.setdefault("oneoffs", {})["oneoff-late"] = {"label": label, "running": True}
            state_path.write_text(json.dumps(st2)); L("LATE oneoff-late created"); sys.exit(143)
        _signal.signal(_signal.SIGTERM, _late)
    import time; time.sleep(float(env.get("HANG_SECONDS", "60")))
if args[:2] == ["ps", "-aq"]:
    flt = args[args.index("--filter") + 1] if "--filter" in args else ""
    want = flt.split("=", 2)[2] if flt.count("=") >= 2 else None
    for cid, c in st.get("oneoffs", {}).items():
        if c["running"] and (want is None or c["label"] == want): out(cid)
    sys.exit(0)
if args[0] in ("stop", "rm") and args[1:2] != ["app"]:
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
        svc = rest[-1]
        if svc == "db": out("dbc")
        else: out(svc + "-cid")
        sys.exit(0)
    if sub == "stop": st["running"] = False; save(); sys.exit(0)
    if sub == "build":
        if env.get("FAIL_BUILD") == rest[-1]: sys.stderr.write("build failed\n"); sys.exit(1)
        sys.exit(0)
    if sub == "config": out("pullup-staging-app\npullup-staging-web"); sys.exit(0)
    if sub == "up": st["running"] = True; st["up_done"] = True; save(); sys.exit(0)
    if sub == "run":
        cmd = " ".join(rest)
        if "alembic heads" in cmd: out(NEW := "b5d8e1f3a6c9 (head)"); sys.exit(0)
        if "alembic upgrade head" in cmd:
            if env.get("FAIL_MIGRATE"): sys.exit(1)
            st["rev"] = "b5d8e1f3a6c9"; save(); sys.exit(0)
        if "python -c" in cmd:
            if env.get("FAIL_CONV_CHECK"): sys.exit(1)
            import subprocess
            k = rest.index("-c")
            sys.exit(subprocess.run([sys.executable, "-c", rest[k + 1], *rest[k + 2:]], input=stdin, text=True).returncode)
        if "repair_plan_convergence" in cmd:
            st["repair_calls"] = st.get("repair_calls", []) + [cmd]; save()
            out('{"mode": "x", "users": 1, "total_mutations": 0, "users_detail": []}'); sys.exit(0)
        if "backfill_multi_program" in cmd:
            st["hist_calls"] = st.get("hist_calls", 0) + 1; save()
            out("DRY-RUN" if "--apply" not in cmd else "Прогон завершён")
            out("копий без изменений: 1")
            unresolved = []
            if env.get("UNRESOLVED"):
                out("Не разрешено (копия НЕ создана, ничего не привязано): 1")
                extra = " x%d" % st["hist_calls"] if env.get("UNRESOLVED_UNSTABLE") else ""
                out("  user_id=57 elective_id=9 pushups 2026-01-01 reps=30: nonstandard_copy_history%s" % extra)
                unresolved = [{"user_id": 57, "elective_id": 9, "reason": "nonstandard_copy_history"}]
            applies = st.get("hist_applies", 0) + (1 if "--apply" in cmd else 0); st["hist_applies"] = applies; save()
            counts = {"unchanged": 1}
            if applies >= 2 and env.get("HIST_REAPPLY_CLASSIFIED"):
                counts["classified"] = 1   # повторный apply «проставил origin» — это изменение, не «без изменений»
            if "--no-result" not in env.get("HIST_FLAGS", ""):
                out("RESULT-JSON " + json.dumps({"mode": "apply" if "--apply" in cmd else "dry-run", "users": 1,
                    "mutations": sum(v for k, v in counts.items() if k in ("classified", "bound", "created", "updated", "superseded", "elective_created")),
                    "counts": counts, "unresolved": unresolved}))
            sys.exit(0)
    sys.exit(0)
if args[0] == "inspect":
    fmt, cid = args[2], args[3]
    if "com.docker.compose.project" in fmt: out(env.get("DB_PROJECT", "pullup-staging"))
    elif ".State.Running" in fmt: out("true" if (cid == "dbc" or st.get("running")) else "false")
    elif ".State.Restarting" in fmt: out("false")
    elif ".State.Health" in fmt: out("healthy")
    elif ".Config.Image" in fmt: out("pullup-staging-" + cid.split("-")[0])
    elif ".Image" in fmt: out(("sha256:built-" + cid.split("-")[0]) if st.get("up_done") and cid != "dbc" else "sha256:old-" + cid.split("-")[0])
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
    if "from users where id in" in sql: out(env.get("KNOWN_USERS", "2")); sys.exit(0)
    if "from training_plans where user_id in" in sql: out(env.get("PLAN_USERS", "12,57")); sys.exit(0)
    if "not exists (select 1 from training_plans" in sql: out(env.get("NOPLAN_USERS", "")); sys.exit(0)
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

SHA256_STUB = """#!/usr/bin/env bash
# настоящий sha256sum; BAD_CHECKSUM=1 — проверка (-c) дампа «не сходится» (повреждённый файл)
if [ "${BAD_CHECKSUM:-}" = "1" ]; then
  for a in "$@"; do [ "$a" = "-c" ] && { echo "sha256sum -c: FAILED" >&2; exit 1; }; done
fi
exec /usr/bin/sha256sum "$@"
"""

CURL_STUB = '#!/usr/bin/env bash\necho "curl $*" >> "$STUB_LOG"\n[ "${FAIL_HEALTH:-}" = "1" ] && exit 22\nexit 0\n'


@pytest.fixture()
def sandbox(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (
        ("docker", DOCKER_STUB),
        ("git", GIT_STUB),
        ("curl", CURL_STUB),
        ("sha256sum", SHA256_STUB),
    ):
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

    base_env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GUARDED_TEST": "1",
        "STAGING_DIR": str(staging),
        "BACKUP_DIR": str(tmp_path / "backups"),
        "HEALTH_URL": "http://127.0.0.1:1/health",
        "STUB_STATE": str(state),
        "STUB_LOG": str(log),
        "TMPDIR": str(tmp_path),
    }

    def run(*args: str, **env: str):
        full = {**base_env, **env}
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
    run.env = base_env  # type: ignore[attr-defined]
    run.root = tmp_path  # type: ignore[attr-defined]
    run.log = log  # type: ignore[attr-defined]
    run.state = state  # type: ignore[attr-defined]
    return run


def idx(lines: list[str], needle: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if needle in lines[i]:
            return i
    return -1


def test_full_success_orders_phases_and_starts_only_at_the_end(sandbox):
    proc, log, state = sandbox(SHA, "apply", "yes", "12,57")
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


def test_dry_run_without_start_never_applies_or_starts(
    sandbox,
):  # dry-run != read-only: миграция выполняется
    proc, log, state = sandbox(SHA, "dry-run", "no")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "services NOT started" in proc.stdout
    assert (
        idx(log, "--apply") == -1
        and idx(log, "--user-ids") == -1
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
        (
            {"UNRESOLVED": "1", "UNRESOLVED_UNSTABLE": "1"},
            "up -d",
        ),  # неразрешённые не стабильны между прогонами
        ({"FAIL_CONV_CHECK": "1"}, "up -d"),  # guard_violations / идемпотентность convergence
        ({"FAIL_CHECK": "after-convergence"}, "up -d"),  # инварианты после convergence
    ],
)
def test_any_failure_after_writers_stopped_leaves_app_and_web_stopped(
    sandbox, env, stage_must_not_run
):
    proc, log, state = sandbox(SHA, "apply", "yes", "12,57", **env)
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
    proc, log, state = sandbox(SHA, "apply", "yes", "12,57", **env)
    assert proc.returncode != 0
    assert "nothing was changed" in proc.stderr
    assert (
        idx(log, "stop app web") == -1
        and idx(log, "docker tag") == -1
        and idx(log, "pg_dump") == -1
    )
    assert state["running"] is True and state["rev"] == OLD_REV


def test_unknown_alembic_revision_is_refused_before_anything_is_stopped(sandbox):
    sandbox.preset(rev="unknown999")
    proc, log, state = sandbox(SHA, "apply", "yes", "12,57", RESTORED_REV="unknown999")
    assert proc.returncode != 0
    assert "unexpected alembic revision" in proc.stderr
    assert "nothing was changed" in proc.stderr
    for mutating in ("docker tag", "stop app web", "pg_dump", "alembic upgrade head", "up -d"):
        assert idx(log, mutating) == -1, mutating
    assert state["running"] is True


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
        (SHA, "apply", "yes", "12,57", "extra"),
        (SHA, "apply", "yes", "12;57"),
        (SHA, "apply", "yes", "all"),
        (SHA, "apply", "yes", "-"),  # apply никогда не применяется ко всем пользователям
        (SHA, "preflight", "yes"),  # preflight не стартует сервисы
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
    for good in (
        f"./deploy-staging-guarded.sh {SHA} preflight no",
        f"./deploy-staging-guarded.sh {SHA} apply no 12,57",
        f"./deploy-staging-guarded.sh {SHA} dry-run no -",
        f"./deploy-staging-guarded.sh {SHA} dry-run no 7",
    ):
        assert rx.fullmatch(good), good
    for bad in (
        f"./deploy-staging-guarded.sh {SHA} apply",
        f"./deploy-staging-guarded.sh {SHA} apply yes; rm -rf /",
        f"./deploy-staging-guarded.sh {SHA} apply yes 12,57; id",
        f"./deploy-staging-guarded.sh {SHA} apply yes 12,",
        f"./deploy-staging-guarded.sh {SHA} apply yes ,12",
        f"./deploy-staging-guarded.sh {SHA} apply yes $(id)",
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


def test_preflight_is_read_only(sandbox):
    proc, log, state = sandbox(SHA, "preflight", "no")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "PREFLIGHT OK (read-only)" in proc.stdout
    for mutating in (
        "stop",
        "docker tag",
        "pg_dump",
        "checkout",
        "build",
        "alembic",
        "up -d",
        "run --rm",
    ):
        assert idx(log, mutating) == -1, (mutating, log)
    assert (
        state["running"] is True and state["rev"] == OLD_REV and state["head"].startswith("4298f8b")
    )


def test_apply_without_confirmed_users_is_refused_before_anything_runs(sandbox):
    proc, log, _state = sandbox(SHA, "apply", "no", "-")
    assert proc.returncode == 2 and log == []
    assert "explicit" in proc.stderr


def test_scope_is_passed_to_both_convergence_scripts_and_all_is_never_applied(sandbox):
    proc, log, _state = sandbox(SHA, "apply", "no", "12,57")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    conv = [
        line
        for line in log
        if "repair_plan_convergence" in line or "backfill_multi_program" in line
    ]
    assert len(conv) == 6  # 2 dry-run + 2 apply на каждый скрипт
    assert all("--user-ids 12,57" in line for line in conv), conv
    assert not any("--all" in line and "--apply" in line for line in conv)


def test_dry_run_without_scope_reads_everyone_and_writes_nothing(sandbox):
    proc, log, _state = sandbox(SHA, "dry-run", "no")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    conv = [line for line in log if "repair_plan_convergence" in line]
    assert conv and all("--all" in line and "--apply" not in line for line in conv)
    assert idx(log, "backfill_multi_program") >= 0 and idx(log, "--apply") == -1


def test_unresolved_electives_are_shown_and_saved_with_user_id_and_reason(sandbox, tmp_path):
    proc, _log, _state = sandbox(SHA, "apply", "no", "12,57", UNRESOLVED="1")
    assert proc.returncode == 0, (
        proc.stderr + proc.stdout
    )  # второй --apply: блок «Не разрешено» не считается правкой
    assert "user_id=57 elective_id=9" in proc.stdout and "nonstandard_copy_history" in proc.stdout
    saved = sorted((tmp_path / "backups").glob("convergence-*/unresolved-*.txt"))
    assert [f.name for f in saved] == ["unresolved-apply.txt", "unresolved-dry-run.txt"]
    assert all("user_id=57" in f.read_text() for f in saved)


# --- сигналы: ненулевой код, fail-safe остановка, one-off контейнеры этого запуска остановлены -------------------


def start_run(
    sandbox_dir: Path, *args: str, stdout=subprocess.PIPE, **env: str
) -> subprocess.Popen:
    full = {**sandbox_dir.env, **env}  # type: ignore[attr-defined]
    return subprocess.Popen(
        ["bash", str(RUN), *args],
        stdout=stdout,
        stderr=subprocess.PIPE,
        text=True,
        env=full,
        cwd=str(sandbox_dir.root),
        stdin=subprocess.DEVNULL,  # type: ignore[attr-defined]
    )


def wait_for_log(log_path: Path, needle: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if needle in log_path.read_text():
            return
        time.sleep(0.1)
    raise AssertionError(f"{needle!r} not reached; log:\n{log_path.read_text()}")


@pytest.mark.parametrize(
    ("hang_on", "after"),
    [
        ("alembic upgrade head", None),  # во время миграции (one-off контейнер compose run)
        (
            "backfill_multi_program.py --converge-history --user-ids 12,57 --apply",
            None,
        ),  # во время сведения
        ("curl", "up -d --no-build app web"),  # после up, во время healthcheck
        ("{{.State.Running}} app-cid", "curl"),  # после healthcheck, до проверки образов
    ],
)
@pytest.mark.parametrize(
    ("sig", "num"), [(signal.SIGTERM, 15), (signal.SIGHUP, 1), (signal.SIGINT, 2)]
)
def test_signal_stops_services_and_this_runs_oneoff_containers(sandbox, hang_on, after, sig, num):
    hang_seconds = (
        "3" if hang_on.startswith("{{") else "60"
    )  # docker inspect в $(…): сигнал обрабатывается после него
    env = {"HANG_ON": hang_on, "HANG_SECONDS": hang_seconds}
    if hang_on == "curl":
        env["FAIL_HEALTH"] = "1"
    proc = start_run(sandbox, SHA, "apply", "yes", "12,57", **env)
    wait_for_log(sandbox.log, f"HANG {hang_on}" if after is None else after)
    if after is not None:
        wait_for_log(sandbox.log, "HANG " + hang_on if hang_on != "curl" else "curl")
    started = time.monotonic()
    proc.send_signal(sig)
    _out, err = proc.communicate(timeout=30)
    elapsed = time.monotonic() - started
    state = json.loads(sandbox.state.read_text())
    log = sandbox.log.read_text().splitlines()
    assert proc.returncode == 128 + num, (proc.returncode, err)
    assert elapsed < 10, (
        f"signal not handled promptly ({elapsed:.1f}s): long commands must run via bgwait"
    )
    assert state["running"] is False, "app/web must be stopped after a signal"
    assert not any(c["running"] for c in state.get("oneoffs", {}).values()), state.get("oneoffs")
    assert f"signal SIG{sig.name[3:]}" in err and "app/web are STOPPED" in err
    report = list((sandbox.root / "backups").glob("guarded-*.FAILED.txt"))
    assert report and f"signal SIG{sig.name[3:]}" in report[0].read_text()
    assert "GUARDED DEPLOY OK" not in _out
    # после сигнала ничего не стартует и не продолжает фазы
    sig_at = max(i for i, line in enumerate(log) if "HANG" in line or "curl" in line)
    assert not any("up -d" in line for line in log[sig_at + 1 :]), log[sig_at:]


def test_oneoff_created_by_the_dying_client_is_also_stopped(sandbox):
    # клиент compose run создаёт контейнер уже после TERM: очистка ждёт выхода клиента и только потом ищет контейнеры
    proc = start_run(
        sandbox, SHA, "apply", "yes", "12,57", HANG_ON="alembic upgrade head", LATE_CREATE="1"
    )
    wait_for_log(sandbox.log, "HANG alembic upgrade head")
    proc.send_signal(signal.SIGTERM)
    _out, err = proc.communicate(timeout=30)
    state = json.loads(sandbox.state.read_text())
    assert proc.returncode == 143, err
    assert "LATE oneoff-late created" in sandbox.log.read_text()
    assert state["oneoffs"]["oneoff-late"]["running"] is False, (
        "one-off created during shutdown must be stopped"
    )
    assert state["running"] is False


def test_closed_stdout_sigpipe_is_a_failure_with_fail_safe_stop(sandbox):
    proc = start_run(
        sandbox, SHA, "apply", "yes", "12,57", HANG_ON="alembic upgrade head", HANG_SECONDS="2"
    )
    assert proc.stdout is not None
    while (
        "[6/9]" not in proc.stdout.readline()
    ):  # читатель вывода исчез (обрыв SSH) во время миграции
        pass
    proc.stdout.close()
    proc.wait(timeout=60)
    state = json.loads(sandbox.state.read_text())
    assert proc.returncode == 141
    assert state["running"] is False
    assert (
        "signal SIGPIPE"
        in next((sandbox.root / "backups").glob("guarded-*.FAILED.txt")).read_text()
    )
    assert idx(sandbox.log.read_text().splitlines(), "up -d") == -1


def test_original_failure_reason_survives_a_signal_during_cleanup(sandbox):
    # healthcheck не прошёл -> очистка; TERM во время очистки игнорируется, причина и код остаются исходными
    proc = start_run(
        sandbox,
        SHA,
        "apply",
        "yes",
        "12,57",
        FAIL_HEALTH="1",
        HEALTH_TIMEOUT="4",
        HANG_ON="label=guarded.run=",
        HANG_SECONDS="3",
    )
    wait_for_log(sandbox.log, "HANG label=guarded.run=")
    proc.send_signal(signal.SIGTERM)
    _out, err = proc.communicate(timeout=30)
    assert proc.returncode == 1, err
    assert "ERROR: healthcheck" in err and "signal SIGTERM" not in err
    assert json.loads(sandbox.state.read_text())["running"] is False


def test_leftover_oneoff_containers_of_a_killed_run_block_the_next_run(sandbox):
    sandbox.preset(oneoffs={"oneoff-9": {"label": "aaaaaaa-old-1", "running": True}})
    proc, log, state = sandbox(SHA, "apply", "yes", "12,57")
    assert proc.returncode != 0 and "one-off containers of an earlier guarded run" in proc.stderr
    assert idx(log, "stop app web") == -1 and state["running"] is True
    assert (
        state["oneoffs"]["oneoff-9"]["running"] is True
    )  # чужое (прежнее) не останавливается автоматически


# --- идемпотентность сведения истории по машинному результату ------------------------------------------------


def test_classified_on_the_second_history_apply_stops_the_rollout(sandbox):
    proc, log, state = sandbox(SHA, "apply", "yes", "12,57", HIST_REAPPLY_CLASSIFIED="1")
    assert proc.returncode != 0
    assert "not idempotent" in proc.stderr
    assert '"classified": 1' in proc.stdout + proc.stderr
    assert idx(log, "up -d") == -1 and state["running"] is False


def test_missing_machine_result_stops_the_rollout(sandbox):
    proc, log, state = sandbox(SHA, "apply", "yes", "12,57", HIST_FLAGS="--no-result")
    assert proc.returncode != 0 and "no RESULT-JSON" in proc.stderr
    assert idx(log, "up -d") == -1 and state["running"] is False


# --- область: план только тем, у кого он есть; история — всем подтверждённым ---------------------------------


def test_user_without_plan_gets_history_only_and_no_plan_is_created(sandbox):
    proc, log, _state = sandbox(SHA, "apply", "no", "12,57", PLAN_USERS="12", NOPLAN_USERS="57")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    repair = [line for line in log if "repair_plan_convergence" in line]
    history = [line for line in log if "backfill_multi_program" in line]
    scope = lambda line: re.search(r"--user-ids (\S+)", line).group(1)
    assert repair and {scope(line) for line in repair} == {"12"}, (
        repair
    )  # план — только тем, у кого он есть
    assert history and {scope(line) for line in history} == {"12,57"}, (
        history
    )  # история — всем подтверждённым
    assert "without plan (history only, no plan is created)=[57]" in proc.stdout


def test_no_user_with_plan_skips_plan_repair_entirely(sandbox):
    proc, log, _state = sandbox(
        SHA, "apply", "no", "57", KNOWN_USERS="1", PLAN_USERS="", NOPLAN_USERS="57"
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert idx(log, "repair_plan_convergence") == -1
    assert idx(log, "backfill_multi_program") >= 0


def test_unknown_user_id_is_refused_in_preflight(sandbox):
    proc, log, state = sandbox(SHA, "apply", "yes", "12,57", KNOWN_USERS="1")
    assert proc.returncode != 0 and "do not exist" in proc.stderr
    assert idx(log, "stop app web") == -1 and state["running"] is True


# --- preflight: app/web до остановки, checksum, манифест ----------------------------------------------------


def test_before_manifest_records_the_exact_image_ids_and_backup_checksum(sandbox, tmp_path):
    proc, _log, _state = sandbox(SHA, "apply", "no", "12,57")
    assert proc.returncode == 0, proc.stderr
    manifest = next((tmp_path / "backups").glob("staging-pre-*.manifest")).read_text()
    assert "app_image_id=sha256:old-app" in manifest and "web_image_id=sha256:old-web" in manifest
    assert "app_compose_image=pullup-staging-app" in manifest
    dump = next((tmp_path / "backups").glob("staging-pre-*.dump"))
    assert f"backup={dump}" in manifest and "backup_sha256=" in manifest


def test_backup_checksum_mismatch_stops_before_the_restore_check(sandbox):
    proc, log, state = sandbox(SHA, "apply", "yes", "12,57", BAD_CHECKSUM="1")
    assert proc.returncode != 0 and "backup checksum does not verify" in proc.stderr
    assert idx(log, "restore_check") == -1 and idx(log, "git checkout") == -1
    assert state["running"] is False and state["rev"] == OLD_REV


def test_dispatcher_drops_test_overrides_before_calling_the_run_script(tmp_path):
    recorder = tmp_path / "run.sh"
    recorder.write_text(
        '#!/usr/bin/env bash\nenv > "$(dirname "$0")/env.txt"\necho "$@" > "$(dirname "$0")/args.txt"\n'
    )
    recorder.chmod(0o755)
    text = (
        DISPATCH.read_text()
        .replace("/home/deploy/deploy-staging-guarded-run.sh", str(recorder))
        .replace(
            "/home/deploy/.deploy-staging.lock",
            str(tmp_path / "lock"),
        )
    )
    dispatcher = tmp_path / "dispatch.sh"
    dispatcher.write_text(text)
    proc = subprocess.run(
        ["bash", str(dispatcher)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": os.environ["PATH"],
            "SSH_ORIGINAL_COMMAND": f"./deploy-staging-guarded.sh {SHA} preflight no",
            "GUARDED_TEST": "1",
            "PROJECT_OVERRIDE": "prod",
            "STAGING_DIR": "/elsewhere",
            "CLEANUP_BIN": "/bin/true",
        },
    )
    assert proc.returncode == 0, proc.stderr
    seen = (tmp_path / "env.txt").read_text()
    for name in ("GUARDED_TEST", "PROJECT_OVERRIDE", "STAGING_DIR", "CLEANUP_BIN"):
        assert f"{name}=" not in seen, name
    assert (tmp_path / "args.txt").read_text().split() == [SHA, "preflight", "no", "-"]


def test_dispatcher_and_old_staging_share_one_lock(tmp_path):
    text = DISPATCH.read_text()
    assert "exec 9>/home/deploy/.deploy-staging.lock" in text and "flock -n 9" in text


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
