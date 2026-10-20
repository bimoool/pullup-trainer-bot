"""Safety mechanics of deploy/rehearse-rest01-release.sh that must hold BEFORE it is run on an owner's host:
the whole process tree of a job dies on an emergency, only this rehearsal's rollback tags are removed (never a general
Docker listing), and resource caps are present for every container and for the dedicated builder."""

import os
import re
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path("deploy/rehearse-rest01-release.sh").resolve()
SRC = SCRIPT.read_text()
PROJECT = "pullup-rehearsal-selftest"


def _bash(tmp_path: Path, body: str, *, docker: str = "", env: dict | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "docker"
    shim.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{tmp_path}/docker.calls"\n{docker}\n')
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    base = tmp_path / "base"
    (base / "backups").mkdir(parents=True, exist_ok=True)
    full_env = {
        **os.environ, "PATH": f"{shim_dir}:{os.environ['PATH']}", "REHEARSE_SOURCE_ONLY": "1",
        "REHEARSE_BASE": str(base), "REHEARSE_PROJECT": PROJECT, **(env or {}),
    }
    return subprocess.run(["bash", "-c", f'source "{SCRIPT}"; set +e; {body}'], capture_output=True, text=True, env=full_env, timeout=timeout, check=False)


def _calls(tmp_path: Path) -> list[str]:
    f = tmp_path / "docker.calls"
    return f.read_text().splitlines() if f.exists() else []


def _alive(pid: int) -> bool:
    """Running or stopped, not dead: a killed process that init has not reaped yet is a zombie (state Z) and does not count."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return False
    return state not in ("Z", "X")


def test_emergency_stop_kills_the_whole_process_tree_including_term_ignoring_children(tmp_path):
    pids = tmp_path / "pids"
    job = (
        f'sleep 300 & echo $! >> "{pids}"; '
        f'( trap "" TERM; sleep 301 ) & echo $! >> "{pids}"; '       # ignores TERM: needs the KILL after the grace period
        f'bash -c "sleep 302 & echo \\$! >> {pids}; wait" & wait'
    )
    body = f'run_job "{tmp_path}/job.log" bash -c \'{job}\' & sleep 2; stop_job_group; wait'
    started = time.time()
    done = _bash(tmp_path, body, timeout=40)
    assert done.returncode == 0, done.stderr
    time.sleep(0.5)
    alive = [int(p) for p in pids.read_text().split() if _alive(int(p))]
    assert not alive, f"processes survived the emergency stop: {alive}"
    assert time.time() - started < 30


def test_job_group_file_is_removed_after_a_normal_job(tmp_path):
    done = _bash(tmp_path, f'run_job "{tmp_path}/j.log" bash -c "exit 7"; echo rc=$?; ls "$BASE/.jobpgid" 2>&1 | head -1')
    assert "rc=7" in done.stdout and "No such file" in done.stdout


def test_rollback_tags_are_removed_only_from_this_rehearsals_manifests(tmp_path):
    base = tmp_path / "base"
    (base / "backups").mkdir(parents=True)
    clone = base / "pullup-trainer-bot"
    good_app, good_web = "local/prod-app:pre-abcdef0-20261020T010203Z", "local/prod-web:pre-abcdef0-20261020T010203Z"

    def manifest(name, project, directory, app, web):
        (base / "backups" / name).write_text(
            f"run_id=x\nproject={project}\ndir={directory}\napp_saved_tag={app}\nweb_saved_tag={web}\n",
        )

    manifest("prod-pre-aaaaaaa-20261020T010203Z.manifest", PROJECT, clone, good_app, good_web)
    manifest("prod-pre-bbbbbbb-20261020T010203Z.manifest", "pullup-trainer-bot", "/root/pullup-trainer-bot",
             "local/prod-app:pre-1111111-20261019T203942Z", "local/prod-web:pre-1111111-20261019T203942Z")  # production's own
    manifest("prod-pre-ccccccc-20261020T010203Z.manifest", PROJECT, "/elsewhere", "local/prod-app:pre-2222222-20261020T010203Z", "x")
    manifest("prod-pre-ddddddd-20261020T010203Z.manifest", PROJECT, clone, "local/prod-app:latest", "pullup-trainer-bot-web:latest")
    done = _bash(tmp_path, "remove_rollback_tags", env={"REHEARSE_BASE": str(base)})
    assert done.returncode == 0, done.stderr
    assert sorted(_calls(tmp_path)) == sorted([f"rmi {good_app}", f"rmi {good_web}"])
    # the old approach listed every local/prod-* tag of the host and diffed it: it must not come back
    assert "docker images" not in SRC and ".tags-before" not in SRC


def test_emergency_stop_touches_only_the_rehearsal_builder_and_project_containers(tmp_path):
    shim = 'if [ "$1" = ps ]; then echo c1; echo c2; fi'
    done = _bash(tmp_path, "emergency_stop", docker=shim)
    assert done.returncode == 0, done.stderr
    calls = _calls(tmp_path)
    assert f"buildx rm --force {PROJECT}-builder" in calls
    assert any(c.startswith(f"ps -q --filter label=com.docker.compose.project={PROJECT}") for c in calls)
    assert "kill c1 c2" in calls
    assert not any("pullup-trainer-bot" in c for c in calls)


def test_nothing_is_done_for_the_production_compose_project(tmp_path):
    done = _bash(tmp_path, "emergency_stop; project_cleanup; echo rc=$?", docker="exit 0", env={"REHEARSE_PROJECT": "pullup-trainer-bot"})
    assert "refusing to touch the production compose project" in done.stderr
    assert _calls(tmp_path) == []


def test_every_container_has_a_hard_memory_cap_without_swap_and_the_builder_is_capped():
    override = SRC.split("cat > docker-compose.override.yml <<YML\n", 1)[1].split("\nYML\n", 1)[0]
    for service in ("db", "redis", "app", "web"):
        block = re.search(rf"^  {service}:\n((?:    .*\n)+)", override + "\n", re.MULTILINE).group(1)
        assert re.search(r"mem_limit: \$\{[A-Z_]+_MB\}m", block), service
        assert re.search(r"memswap_limit: \$\{[A-Z_]+_MB\}m", block), service
        limit = re.search(r"mem_limit: (\S+)", block).group(1)
        assert re.search(r"memswap_limit: " + re.escape(limit), block), f"{service}: swap must equal the memory cap"
        assert "cpus:" in block and "pids_limit:" in block
    assert 'docker update --memory="${BUILD_MEM_MB}m" --memory-swap="${BUILD_MEM_MB}m"' in SRC
    assert "refusing to build without a hard cap" in SRC
    # the start gate is the SUM of all caps plus a host reserve, not a magic number
    assert "MIN_MEM_MB=\"${REHEARSE_MIN_MEM_MB:-$((BUILD_MEM_MB + DB_MEM_MB + REDIS_MEM_MB + PROD_FLOOR_MB))}\"" in SRC


@pytest.mark.parametrize("runner_env", ["BUILDX_BUILDER=\"$BUILDER\"", "PROD_PROJECT=\"$PROJECT\""])
def test_runner_builds_with_the_capped_builder_and_in_the_rehearsal_project(runner_env):
    block = SRC.split("run_runner() {", 1)[1].split("\n}\n", 1)[0]
    assert runner_env in block and "run_job" in block
