"""Exercise cloud patch acceptance/rejection in real temporary Git repositories."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "codex_patch_guard", Path(__file__).resolve().parents[2] / "scripts/codex_patch_guard.py"
)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


@pytest.mark.parametrize(
    "path",
    [
        "app/web/auth.py",
        "tests/test_web/test_auth.py",
        "webapp-frontend/src/App.tsx",
        "docs/audit/bug.md",
    ],
)
def test_ordinary_paths(path):
    assert guard.allowed_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "../app/evil.py",
        "/app/evil.py",
        "app/../.github/workflows/ci.yml",
        ".github/workflows/ci.yml",
        "scripts/orch.py",
        "deploy/run.sh",
        ".env",
        "app/db/migrations/versions/change.py",
        "app/.env",
        "app/key.pem",
        "webapp-frontend/node_modules/pkg/a.js",
        "tests/evil\nname.py",
        "app\\evil.py",
        "webapp-frontend/package.json",
        "webapp-frontend/package-lock.json",
        "app/db/models.py",
    ],
)
def test_forbidden_paths(path):
    assert not guard.allowed_path(path)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.chdir(root)
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "config", "user.name", "test"], check=True)
    (root / "app").mkdir()
    (root / "app/example.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-qm", "base"], check=True)
    return root


def patch_for(repo, destination, content, *, mode=None):
    target = repo / destination
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    if mode:
        target.chmod(mode)
    subprocess.run(["git", "add", "."], check=True)
    patch = repo.parent / "change.patch"
    patch.write_bytes(subprocess.check_output(["git", "diff", "--cached", "--binary"]))
    subprocess.run(["git", "reset", "--hard", "-q"], check=True)
    return patch


def test_apply_regular_code_patch(repo):
    patch = patch_for(repo, "app/example.py", "VALUE = 2\n")
    guard.apply_patch(patch)
    assert (repo / "app/example.py").read_text() == "VALUE = 2\n"


def test_reject_workflow_edit(repo):
    patch = patch_for(repo, ".github/workflows/pwn.yml", "name: unsafe\n")
    with pytest.raises(ValueError, match="forbidden change"):
        guard.apply_patch(patch)


def test_reject_executable(repo):
    patch = patch_for(repo, "app/example.py", "VALUE = 2\n", mode=0o755)
    with pytest.raises(ValueError, match="non-executable"):
        guard.apply_patch(patch)


def test_reject_symlink(repo):
    target = repo / "app/link"
    target.symlink_to("/etc/passwd")
    subprocess.run(["git", "add", "."], check=True)
    patch = repo.parent / "change.patch"
    patch.write_bytes(subprocess.check_output(["git", "diff", "--cached", "--binary"]))
    subprocess.run(["git", "reset", "--hard", "-q"], check=True)
    with pytest.raises(ValueError, match="non-executable"):
        guard.apply_patch(patch)


def test_reject_deletion(repo):
    (repo / "app/example.py").unlink()
    subprocess.run(["git", "add", "."], check=True)
    patch = repo.parent / "change.patch"
    patch.write_bytes(subprocess.check_output(["git", "diff", "--cached", "--binary"]))
    subprocess.run(["git", "reset", "--hard", "-q"], check=True)
    with pytest.raises(ValueError, match="forbidden change"):
        guard.apply_patch(patch)
