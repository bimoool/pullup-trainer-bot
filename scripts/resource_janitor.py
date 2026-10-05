#!/usr/bin/env python3
"""Local resource janitor: audit worktrees / stale test servers / Docker, clean only what is provably safe.

    python scripts/resource_janitor.py audit
    python scripts/resource_janitor.py local-clean --dry-run     # default
    python scripts/resource_janitor.py local-clean --apply

Safety model (docs/RESOURCE_LIFECYCLE.md):
  * DEFAULT IS DRY RUN. Nothing is touched without an explicit --apply.
  * A worktree is removed only if EVERY predicate in `worktree_verdict` holds. Anything dirty,
    unpushed, canonical, the current one, in use by a process, or whose state could not be
    determined is refused (unknown == unsafe).
  * Removal uses plain `git worktree remove` (never --force) and `git branch -d` (never -D), so git
    itself is a second line of defence.
  * Docker: only dangling images and old BuildKit cache. Volumes are NEVER touched; every docker
    command goes through `assert_no_volume_command`.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

CANONICAL_REF = "origin/develop/current"
PROTECTED_BRANCHES = frozenset({"main", "develop/current"})
# Test servers started by parallel agents / E2E runs. Port 8001 is the default local dev/E2E port
# and may belong to someone's live session, so it is deliberately outside the range.
TEST_PORT_RANGE = range(8011, 8100)
GENERATED_DIRS = (
    "playwright-report",
    "test-results",
    ".pytest_cache",
    ".ruff_cache",
    "ux-captures",
    "webapp-frontend/dist",
    "webapp-frontend/e2e/playwright-report",
    "webapp-frontend/e2e/test-results",
)
TMP_PATTERNS = ("par-e2e-*", "par_env_*.sh", "orch-e2e")
GB = 1024**3


# ---------------------------------------------------------------- safety predicates (pure; tested)


@dataclass(frozen=True)
class WorktreeInfo:
    path: str
    branch: str  # "" when detached
    head: str
    size_bytes: int | None
    is_primary: bool  # the checkout `git worktree list` prints first
    is_current: bool  # contains the cwd of this process
    dirty: bool | None  # tracked changes
    untracked: bool | None
    pushed: bool | None  # some remote-tracking ref contains HEAD
    reachable: bool | None  # HEAD is an ancestor of origin/develop/current
    in_use_by: tuple[int, ...] | None  # pids whose cwd is inside the worktree; None = unknown
    shared_by: tuple[str, ...] = ()  # other worktrees whose .venv/node_modules symlink into this one
    foreign: bool = False  # lives in another session's scratchpad, not ours to remove


def worktree_verdict(w: WorktreeInfo) -> tuple[bool, str]:
    """(safe_to_remove, reason). Every refusal names the first failing predicate."""
    if w.is_primary:
        return False, "primary/canonical checkout"
    if w.branch in PROTECTED_BRANCHES:
        return False, f"canonical branch {w.branch}"
    if w.is_current:
        return False, "current working directory"
    if w.foreign:
        return False, "lives in a session scratchpad (owned by another session)"
    if w.shared_by:
        names = ",".join(Path(p).name for p in w.shared_by[:3])
        return False, f"hosts shared .venv/node_modules used by {names}"
    if w.dirty is None or w.untracked is None or w.pushed is None or w.reachable is None:
        return False, "state unknown"
    if w.in_use_by is None:
        return False, "process usage unknown"
    if w.in_use_by:
        return False, f"in use by pid {','.join(map(str, w.in_use_by))}"
    if w.dirty:
        return False, "dirty (tracked changes)"
    if w.untracked:
        return False, "untracked files"
    if not (w.pushed or w.reachable):
        return False, "HEAD unpushed and not in develop/current"
    return True, "clean, preserved remotely" + (", integrated" if w.reachable else "")


def assert_no_volume_command(argv: list[str]) -> None:
    """Hard guard: the janitor must never issue a docker command that can touch volumes."""
    lowered = [a.lower() for a in argv]
    if argv and Path(argv[0]).name == "docker" and {"volume", "--volumes", "-v", "system"} & set(lowered):
        raise RuntimeError(f"refusing docker command that may touch volumes: {argv}")


def is_stale_test_server(args: str, port: int | None, age_s: int, min_age_s: int) -> bool:
    """A forgotten local uvicorn: test-port range, app.web.main, old enough not to be a live run."""
    return (
        "uvicorn" in args
        and "app.web.main:app" in args
        and port is not None
        and port in TEST_PORT_RANGE
        and age_s >= min_age_s
    )


def parse_etime(etime: str) -> int:
    """ps etime ([[dd-]hh:]mm:ss) -> seconds."""
    days = 0
    if "-" in etime:
        d, etime = etime.split("-", 1)
        days = int(d)
    parts = [int(p) for p in etime.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return ((days * 24 + h) * 60 + m) * 60 + s


def is_removable_artifact(path: Path, root: Path, age_s: float, min_age_s: float) -> bool:
    """Generated artifact dir inside `root`, old enough, not a symlink escaping the tree."""
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return not path.is_symlink() and age_s >= min_age_s


# ---------------------------------------------------------------- data collection


def run(argv: list[str], cwd: str | None = None) -> tuple[int, str]:
    assert_no_volume_command(argv)
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)
    return p.returncode, p.stdout.strip()


def du_bytes(path: str) -> int | None:
    rc, out = run(["du", "-sk", path])  # does not follow symlinks (shared venv/node_modules stay out)
    return int(out.split()[0]) * 1024 if rc == 0 and out else None


def process_cwds() -> dict[int, str] | None:
    rc, out = run(["lsof", "-d", "cwd", "-Fpn"])
    if rc not in (0, 1) or not out:
        return None
    cwds: dict[int, str] = {}
    pid = 0
    for line in out.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid:
            cwds[pid] = line[1:]
    return cwds


SHARED_LINKS = (".venv", "node_modules", "webapp-frontend/node_modules", "webapp-frontend/e2e/node_modules")


def shared_dep_hosts(paths: list[str]) -> dict[str, list[str]]:
    """host worktree -> consumer worktrees whose venv/node_modules are symlinks pointing into it."""
    reals = {p: os.path.realpath(p) for p in paths}
    hosts: dict[str, list[str]] = {}
    for consumer in paths:
        for rel in SHARED_LINKS:
            link = Path(consumer, rel)
            if not link.is_symlink():
                continue
            target = os.path.realpath(link)
            for host, real in reals.items():
                if host != consumer and (target == real or target.startswith(real + os.sep)):
                    hosts.setdefault(host, [])
                    if consumer not in hosts[host]:
                        hosts[host].append(consumer)
    return hosts


def is_foreign_scratchpad(path: str) -> bool:
    real = os.path.realpath(path)
    return bool(re.match(r"^(/private)?/tmp/claude-\d+/", real)) and "scratchpad" in real


def list_worktrees(repo: str) -> list[WorktreeInfo]:
    rc, out = run(["git", "worktree", "list", "--porcelain"], cwd=repo)
    if rc != 0:
        sys.exit(f"git worktree list failed: {out}")
    cwds = process_cwds()
    cwd_now = os.path.realpath(os.getcwd())
    me = os.getpid()
    infos: list[WorktreeInfo] = []
    all_paths = [
        ln.split(" ", 1)[1] for ln in out.splitlines() if ln.startswith("worktree ") and os.path.isdir(ln.split(" ", 1)[1])
    ]
    hosts = shared_dep_hosts(all_paths)
    for i, block in enumerate(out.split("\n\n")):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines() if line)
        path = fields.get("worktree")
        if not path:
            continue
        branch = fields.get("branch", "").removeprefix("refs/heads/")
        head = fields.get("HEAD", "")[:9]
        real = os.path.realpath(path)
        if not os.path.isdir(path):
            infos.append(WorktreeInfo(path, branch, head, None, i == 0, False, None, None, None, None, None))
            continue
        rc_s, status = run(["git", "status", "--porcelain"], cwd=path)
        lines = status.splitlines() if rc_s == 0 else []
        rc_r, remotes = run(["git", "branch", "-r", "--contains", "HEAD"], cwd=path)
        rc_a = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "HEAD", CANONICAL_REF], cwd=path, capture_output=True, check=False
        ).returncode
        users: tuple[int, ...] | None = None
        if cwds is not None:
            users = tuple(
                sorted(
                    p
                    for p, c in cwds.items()
                    if p != me and (os.path.realpath(c) == real or os.path.realpath(c).startswith(real + os.sep))
                )
            )
        infos.append(
            WorktreeInfo(
                path=path,
                branch=branch,
                head=head,
                size_bytes=du_bytes(path),
                is_primary=i == 0,
                is_current=cwd_now == real or cwd_now.startswith(real + os.sep),
                dirty=None if rc_s != 0 else any(not ln.startswith("??") for ln in lines),
                untracked=None if rc_s != 0 else any(ln.startswith("??") for ln in lines),
                pushed=None if rc_r != 0 else bool(remotes),
                reachable=None if rc_a not in (0, 1) else rc_a == 0,
                in_use_by=users,
                shared_by=tuple(hosts.get(path, ())),
                foreign=is_foreign_scratchpad(path),
            )
        )
    return infos


def listening_test_servers(min_age_s: int) -> list[tuple[int, int, int, str]]:
    """[(pid, port, age_s, args)] for stale local uvicorn test servers."""
    rc, out = run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"])
    if rc not in (0, 1):
        return []
    found = []
    pid = 0
    for line in out.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid:
            m = re.search(r":(\d+)$", line)
            if not m:
                continue
            port = int(m.group(1))
            _, args = run(["ps", "-o", "args=", "-p", str(pid)])
            _, et = run(["ps", "-o", "etime=", "-p", str(pid)])
            if args and et:
                age = parse_etime(et.strip())
                if is_stale_test_server(args, port, age, min_age_s):
                    found.append((pid, port, age, args[-90:]))
    return sorted(found, key=lambda t: t[1])


def fmt_size(n: int | None) -> str:
    if n is None:
        return "?"
    return f"{n / GB:.2f}G" if n >= GB else f"{n / 1024**2:.0f}M"


def print_worktrees(infos: list[WorktreeInfo]) -> list[tuple[WorktreeInfo, bool, str]]:
    rows = []
    print(f"{'PATH':44} {'BRANCH':34} {'HEAD':9} {'SIZE':6} {'STATE':5} {'PUSHED':6} {'IN-DEV':6} {'VERDICT':6} REASON")
    for w in infos:
        safe, reason = worktree_verdict(w)
        rows.append((w, safe, reason))
        state = "?" if w.dirty is None else ("DIRTY" if (w.dirty or w.untracked) else "clean")
        yn = lambda v: "?" if v is None else ("yes" if v else "no")
        print(
            f"{Path(w.path).name[:44]:44} {(w.branch or '(detached)')[:34]:34} {w.head:9} {fmt_size(w.size_bytes):6} "
            f"{state:5} {yn(w.pushed):6} {yn(w.reachable):6} {'SAFE' if safe else 'UNSAFE':6} {reason}"
        )
    return rows


# ---------------------------------------------------------------- commands


def disk_free_gb() -> float:
    u = shutil.disk_usage(os.path.expanduser("~"))
    return u.free / GB


def cmd_audit(repo: str, args: argparse.Namespace) -> int:
    print(f"== disk free (home volume): {disk_free_gb():.1f} GB")
    rc, _ = run(["git", "rev-parse", "--verify", "--quiet", CANONICAL_REF], cwd=repo)
    if rc != 0:
        print(f"!! {CANONICAL_REF} missing: run `git fetch --prune` first (every worktree will be UNSAFE)")
    print("\n== worktrees")
    rows = print_worktrees(list_worktrees(repo))
    safe = [r for r in rows if r[1]]
    print(f"-> {len(rows)} worktrees, {len(safe)} removable, {sum(r[0].size_bytes or 0 for r in safe) / GB:.2f} GB in removable")
    print("\n== stale local test servers (uvicorn app.web.main, ports 8011-8099)")
    servers = listening_test_servers(args.min_server_age_hours * 3600)
    for pid, port, age, cmd in servers:
        print(f"  pid {pid:<7} :{port}  age {age // 3600}h{age % 3600 // 60:02d}m  ...{cmd}")
    print(f"-> {len(servers)} stale servers")
    print("\n== /tmp project dirs")
    for pat in TMP_PATTERNS:
        for p in sorted(Path("/tmp").glob(pat)):
            print(f"  {p}  {fmt_size(du_bytes(str(p)))}")
    print("\n== docker (read only)")
    if shutil.which("docker"):
        # `docker system df` is read-only but trips the volume guard on 'system'; use per-object listings.
        print(run(["docker", "ps", "-a", "--size", "--format", "{{.Names}}\t{{.Status}}\t{{.Size}}"])[1])
        print(run(["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}"])[1])
        print("build cache:", " | ".join(run(["docker", "builder", "du"])[1].splitlines()[-3:]))
    return 0


def cmd_local_clean(repo: str, args: argparse.Namespace) -> int:
    apply = args.apply
    mode = "APPLY" if apply else "DRY-RUN (nothing will be changed; pass --apply)"
    print(f"== local-clean: {mode}")
    before = disk_free_gb()
    rows = print_worktrees(list_worktrees(repo))
    removed = 0
    for w, safe, _ in rows:
        if not safe:
            continue
        print(f"{'REMOVE' if apply else 'would remove'} worktree {w.path}")
        if apply:
            rc, out = run(["git", "worktree", "remove", w.path], cwd=repo)  # no --force, ever
            if rc != 0:
                print(f"  refused by git: {out}")
                continue
            removed += 1
            if w.branch and w.branch not in PROTECTED_BRANCHES:
                rc, out = run(["git", "branch", "-d", w.branch], cwd=repo)  # -d: git re-checks merged state
                print(f"  branch {w.branch}: {'deleted' if rc == 0 else 'kept (' + out.splitlines()[0] + ')' if out else 'kept'}")
    if apply:
        run(["git", "worktree", "prune"], cwd=repo)

    for pid, port, age, cmd in listening_test_servers(args.min_server_age_hours * 3600):
        print(f"{'SIGTERM' if apply else 'would stop'} stale test server pid {pid} :{port} (age {age // 3600}h)")
        if apply:
            os.kill(pid, signal.SIGTERM)

    min_age = args.min_artifact_age_days * 86400
    now = time.time()
    remaining = [w for w, safe, _ in rows if not (safe and apply)]
    for w in remaining:
        if w.in_use_by:  # never clean artifacts a live process might be writing
            continue
        root = Path(w.path)
        for rel in GENERATED_DIRS:
            d = root / rel
            if d.is_dir() and is_removable_artifact(d, root, now - d.stat().st_mtime, min_age):
                print(f"{'REMOVE' if apply else 'would remove'} artifact {d} ({fmt_size(du_bytes(str(d)))})")
                if apply:
                    shutil.rmtree(d, ignore_errors=True)
    for pat in TMP_PATTERNS:
        for p in Path("/tmp").glob(pat):
            if p.is_symlink() or now - p.stat().st_mtime < min_age:
                continue
            print(f"{'REMOVE' if apply else 'would remove'} tmp {p}")
            if apply:
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)

    if shutil.which("docker") and run(["docker", "version", "--format", "ok"])[0] == 0:
        for argv in (
            ["docker", "image", "prune", "-f"],  # dangling only (no -a)
            ["docker", "builder", "prune", "-f", "--filter", f"until={args.docker_cache_hours}h"],
        ):
            print(f"{'RUN' if apply else 'would run'}: {' '.join(argv)}")
            if apply:
                out = run(argv)[1].splitlines()
                print("  " + (out[-1] if out else "(nothing)"))
    print(f"\nremoved worktrees: {removed}; disk free {before:.1f} -> {disk_free_gb():.1f} GB")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="any checkout/worktree of the repository")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("audit", "local-clean"):
        sp = sub.add_parser(name)
        sp.add_argument("--min-server-age-hours", type=int, default=2)
        if name == "local-clean":
            sp.add_argument("--min-artifact-age-days", type=int, default=3)
            sp.add_argument("--docker-cache-hours", type=int, default=168)
            g = sp.add_mutually_exclusive_group()
            g.add_argument("--dry-run", action="store_true", help="default")
            g.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    repo = str(Path(args.repo).resolve())
    return cmd_audit(repo, args) if args.cmd == "audit" else cmd_local_clean(repo, args)


if __name__ == "__main__":
    sys.exit(main())
