"""Constrain an untrusted cloud patch before tests or publication; no network/DB."""

import argparse
import subprocess
from pathlib import Path, PurePosixPath

MAX_PATCH_BYTES = 2_000_000
MAX_FILES = 40


def allowed_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts or any(part in {"..", ".git", "node_modules"} for part in parts):
        return False
    if path.startswith("/") or "\\" in path or any(ord(c) < 32 for c in path):
        return False
    if any(part.startswith(".") for part in parts):
        return False
    if (
        path.startswith("app/db/migrations/")
        or path == "app/db/models.py"
        or path.endswith((".pem", ".key", ".env"))
    ):
        return False
    return path.startswith(
        (
            "app/",
            "tests/",
            "webapp-frontend/src/",
            "webapp-frontend/tests/",
            "webapp-frontend/e2e/scenarios/",
            "docs/audit/",
        )
    )


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def validate_staged() -> None:
    changes = git("diff", "--cached", "--name-status", "--no-renames", "-z").split(b"\0")
    changes = changes[:-1] if changes[-1] == b"" else changes
    if not changes or len(changes) % 2:
        raise ValueError("empty or malformed patch")
    if len(changes) // 2 > MAX_FILES:
        raise ValueError("patch exceeds file limit")
    for status, raw_path in zip(changes[::2], changes[1::2], strict=True):
        path = raw_path.decode("utf-8")
        if status not in (b"A", b"M") or not allowed_path(path):
            raise ValueError(f"forbidden change: {status.decode()} {path}")
        entry = git("ls-files", "--stage", "--", path).decode()
        if not entry.startswith("100644 "):
            raise ValueError(f"only regular non-executable files allowed: {path}")


def apply_patch(path: Path) -> None:
    if not 0 < path.stat().st_size <= MAX_PATCH_BYTES:
        raise ValueError("empty or oversized patch")
    if git("status", "--porcelain"):
        raise ValueError("requires clean checkout")
    subprocess.run(["git", "apply", "--check", "--", str(path.resolve())], check=True)
    subprocess.run(["git", "apply", "--index", "--", str(path.resolve())], check=True)
    # A rejected patch stays staged for inspection on a disposable runner; never committed/pushed.
    validate_staged()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("patch", type=Path)
    args = parser.parse_args()
    apply_patch(args.patch)
