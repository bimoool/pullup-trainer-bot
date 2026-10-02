"""Safety predicates of scripts/resource_janitor.py: the janitor may only ever delete provably safe things."""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import pytest

from scripts import resource_janitor as rj

SAFE = rj.WorktreeInfo(
    path="/w/pullup-par-x",
    branch="parallel/x",
    head="abc123456",
    size_bytes=1,
    is_primary=False,
    is_current=False,
    dirty=False,
    untracked=False,
    pushed=True,
    reachable=True,
    in_use_by=(),
)


def verdict(**kw):
    return rj.worktree_verdict(dataclasses.replace(SAFE, **kw))


def test_clean_pushed_integrated_worktree_is_safe():
    assert verdict()[0] is True


def test_pushed_but_not_integrated_is_still_safe():
    assert verdict(reachable=False)[0] is True


def test_integrated_but_not_pushed_is_safe():
    assert verdict(pushed=False)[0] is True


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"is_primary": True}, "primary"),
        ({"branch": "develop/current"}, "canonical"),
        ({"branch": "main"}, "canonical"),
        ({"is_current": True}, "current"),
        ({"dirty": True}, "dirty"),
        ({"untracked": True}, "untracked"),
        ({"pushed": False, "reachable": False}, "unpushed"),
        ({"in_use_by": (4242,)}, "in use"),
        ({"shared_by": ("/w/pullup-par-y",)}, "shared"),
        ({"foreign": True}, "scratchpad"),
        ({"dirty": None}, "unknown"),
        ({"untracked": None}, "unknown"),
        ({"pushed": None}, "unknown"),
        ({"reachable": None}, "unknown"),
        ({"in_use_by": None}, "unknown"),
    ],
)
def test_unsafe_worktrees_are_refused(override, fragment):
    safe, reason = verdict(**override)
    assert safe is False
    assert fragment in reason


def test_shared_dep_host_detection(tmp_path: Path):
    host, consumer, other = (tmp_path / n for n in ("host", "consumer", "other"))
    for d in (host / "webapp-frontend" / "node_modules", host / ".venv", consumer / "webapp-frontend", other):
        d.mkdir(parents=True)
    (consumer / ".venv").symlink_to(host / ".venv")
    (consumer / "webapp-frontend" / "node_modules").symlink_to(host / "webapp-frontend" / "node_modules")
    found = rj.shared_dep_hosts([str(host), str(consumer), str(other)])
    assert found == {str(host): [str(consumer)]}


def test_foreign_scratchpad_detection():
    assert rj.is_foreign_scratchpad("/private/tmp/claude-502/-Users-x/abc/scratchpad/wt1")
    assert not rj.is_foreign_scratchpad("/Users/x/Documents/Claude Code/pullup-par-a")


def test_detached_head_follows_same_rules():
    assert verdict(branch="")[0] is True
    assert verdict(branch="", pushed=False, reachable=False)[0] is False


@pytest.mark.parametrize(
    "argv",
    [
        ["docker", "volume", "prune", "-f"],
        ["docker", "volume", "rm", "x"],
        ["docker", "system", "prune", "--volumes"],
        ["docker", "system", "prune", "-a"],
        ["docker", "image", "prune", "--volumes"],
        ["docker", "rm", "-v", "c"],
        ["/usr/local/bin/docker", "volume", "ls"],
    ],
)
def test_docker_volume_commands_are_blocked(argv):
    with pytest.raises(RuntimeError):
        rj.assert_no_volume_command(argv)
    with pytest.raises(RuntimeError):
        rj.run(argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["docker", "image", "prune", "-f"],
        ["docker", "builder", "prune", "-f", "--filter", "until=168h"],
        ["docker", "ps", "-a"],
        ["git", "worktree", "remove", "/x"],
    ],
)
def test_allowed_commands_pass_guard(argv):
    rj.assert_no_volume_command(argv)


def test_janitor_source_never_requests_force_or_volume_cleanup():
    src = Path(rj.__file__).read_text()
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith(("#", '"""')))
    assert '"--force"' not in code and "'--force'" not in code
    assert '"-D"' not in code
    # the only place a volume flag may appear is the guard that rejects it
    offenders = [ln for ln in code.splitlines() if '"--volumes"' in ln or '"volume"' in ln]
    assert all("set(lowered)" in ln for ln in offenders)


def test_stale_server_detection():
    cmd = "/x/.venv/bin/uvicorn app.web.main:app --port 8022"
    two_h = 2 * 3600
    assert rj.is_stale_test_server(cmd, 8022, two_h, two_h)
    assert not rj.is_stale_test_server(cmd, 8022, two_h - 1, two_h)  # a live run is not stale
    assert not rj.is_stale_test_server(cmd, 8001, 99999, two_h)  # default dev/E2E port is never touched
    assert not rj.is_stale_test_server(cmd, 5432, 99999, two_h)
    assert not rj.is_stale_test_server("postgres -D /data", 8022, 99999, two_h)
    assert not rj.is_stale_test_server(cmd, None, 99999, two_h)


@pytest.mark.parametrize(
    ("etime", "seconds"),
    [("05:09", 309), ("01:02:03", 3723), ("2-00:00:01", 172801), ("00:00", 0)],
)
def test_parse_etime(etime, seconds):
    assert rj.parse_etime(etime) == seconds


def test_artifact_must_be_old_and_inside_root(tmp_path: Path):
    root = tmp_path / "wt"
    (root / "test-results").mkdir(parents=True)
    inside = root / "test-results"
    day = 86400
    assert rj.is_removable_artifact(inside, root, 4 * day, 3 * day)
    assert not rj.is_removable_artifact(inside, root, 1 * day, 3 * day)  # too fresh

    outside = tmp_path / "shared-node_modules"
    outside.mkdir()
    link = root / "playwright-report"
    link.symlink_to(outside)
    assert not rj.is_removable_artifact(link, root, 99 * day, 3 * day)  # symlink escaping the tree


def _git(cwd: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def test_list_worktrees_flags_dirty_and_unpushed(tmp_path: Path, monkeypatch):
    """End-to-end on a throwaway repo: dirty/unpushed worktrees must come out UNSAFE."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "develop/current", str(origin))
    repo = tmp_path / "repo"
    _git(tmp_path, "clone", str(origin), str(repo))
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-b", "develop/current")
    (repo / "a.txt").write_text("a")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "init")
    _git(repo, "push", "-u", "origin", "develop/current")

    clean = tmp_path / "wt-clean"
    dirty = tmp_path / "wt-dirty"
    unpushed = tmp_path / "wt-unpushed"
    _git(repo, "worktree", "add", "-b", "feat/clean", str(clean), "develop/current")
    _git(repo, "worktree", "add", "-b", "feat/dirty", str(dirty), "develop/current")
    _git(repo, "worktree", "add", "-b", "feat/unpushed", str(unpushed), "develop/current")
    (dirty / "a.txt").write_text("changed")
    (unpushed / "b.txt").write_text("b")
    _git(unpushed, "add", "b.txt")
    _git(unpushed, "commit", "-m", "local only")

    monkeypatch.chdir(tmp_path)  # cwd outside every worktree
    monkeypatch.setattr(rj, "process_cwds", dict)
    verdicts = {Path(w.path).name: rj.worktree_verdict(w) for w in rj.list_worktrees(str(repo))}

    assert verdicts["repo"][0] is False  # primary
    assert verdicts["wt-clean"][0] is True
    assert verdicts["wt-dirty"][0] is False and "dirty" in verdicts["wt-dirty"][1]
    assert verdicts["wt-unpushed"][0] is False and "unpushed" in verdicts["wt-unpushed"][1]


def test_unknown_process_state_blocks_removal(tmp_path: Path, monkeypatch):
    origin = tmp_path / "o.git"
    _git(tmp_path, "init", "--bare", "-b", "develop/current", str(origin))
    repo = tmp_path / "r"
    _git(tmp_path, "clone", str(origin), str(repo))
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-b", "develop/current")
    (repo / "a").write_text("a")
    _git(repo, "add", "a")
    _git(repo, "commit", "-m", "i")
    _git(repo, "push", "-u", "origin", "develop/current")
    _git(repo, "worktree", "add", "-b", "f", str(tmp_path / "w"), "develop/current")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rj, "process_cwds", lambda: None)  # lsof unavailable
    by_name = {Path(w.path).name: rj.worktree_verdict(w) for w in rj.list_worktrees(str(repo))}
    assert by_name["w"][0] is False and "unknown" in by_name["w"][1]
