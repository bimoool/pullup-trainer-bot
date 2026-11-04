"""Docs-only optimization must never hide code changes or missing API data."""

import importlib.util
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ci_changed_paths", ROOT / "scripts/ci_changed_paths.py"
)
paths = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paths)
HEAD, BASE = "a" * 40, "b" * 40


def file(path, status="modified", **extra):
    return {"filename": path, "status": status, **extra}


@pytest.mark.parametrize("status", ["added", "modified", "removed"])
def test_known_markdown_only_can_skip(status):
    assert not paths.run_full([file("docs/audit/review.md", status), file("README.md")])


@pytest.mark.parametrize(
    "name",
    [
        "app/db/migrations/versions/new.py",
        ".github/workflows/tests.yml",
        ".github/workflows/e2e.yml",
        ".github/workflows/unknown.yml",
        "scripts/tool.py",
        "tests/test_something.py",
        "app/web/auth.py",
        "contracts/new.json",
        "pyproject.toml",
        "Dockerfile.web",
        "docker-compose.yml",
        "deploy/run.sh",
        "webapp-frontend/src/App.tsx",
        "unknown.md",
        "docs/rehearsal/query.sql",
        "docs/tool.py",
        "docs/x.md/../../app/auth.py",
        "/docs/a.md",
        "docs//a.md",
        "docs/./a.md",
        "docs/../a.md",
        "docs/.hidden.md",
        "docs/a.md\n",
        "docs\\a.md",
    ],
)
def test_code_ci_migration_scripts_and_unknown_paths_run_full(name):
    assert paths.run_full([file(name)])


def test_rename_checks_old_and_new_paths():
    assert paths.run_full([file("docs/renamed.md", "renamed", previous_filename="scripts/code.py")])
    assert paths.run_full([file("scripts/code.py", "renamed", previous_filename="docs/renamed.md")])
    assert not paths.run_full([file("docs/new.md", "renamed", previous_filename="docs/old.md")])
    assert paths.run_full([file("docs/new.md", "renamed")])


@pytest.mark.parametrize(
    "files",
    [[], None, {}, [None], [{}], [file("docs/a.md", "copied")], [file("docs/a.md", "unexpected")]],
)
def test_unknown_or_missing_change_metadata_runs_full(files):
    assert paths.run_full(files)


class API:
    def __init__(self, count, batches, *, after_head=HEAD, after_base=BASE, after_count=None):
        self.count, self.batches = count, batches
        self.after_head, self.after_base = after_head, after_base
        self.after_count = count if after_count is None else after_count
        self.reads = 0
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        if path == "pulls/365":
            self.reads += 1
            return {
                "head": {"sha": HEAD if self.reads == 1 else self.after_head},
                "base": {"sha": BASE if self.reads == 1 else self.after_base},
                "changed_files": self.count if self.reads == 1 else self.after_count,
            }
        return self.batches[int(path.rsplit("=", 1)[1]) - 1]


def collect(api):
    return paths.changed_files(api, 365, HEAD, BASE)


def test_second_page_code_change_never_skipped():
    docs = [file(f"docs/{n}.md") for n in range(100)]
    api = API(101, [docs, [file("app/domain/rules.py")]])
    assert paths.run_full(collect(api))
    assert len(api.calls) == 4


def test_exact_page_boundary_requires_empty_following_page():
    docs = [file(f"docs/{n}.md") for n in range(100)]
    api = API(100, [docs, []])
    assert not paths.run_full(collect(api))
    assert "page=2" in api.calls[2]


@pytest.mark.parametrize("count", [0, None, "1", 3000, 3001, True])
def test_cap_or_unknown_count_refuses_skip(count):
    with pytest.raises(ValueError):
        collect(API(count, [[]]))


def test_truncated_response_refuses_skip():
    with pytest.raises(ValueError, match="incomplete"):
        collect(API(2, [[file("docs/a.md")]]))


@pytest.mark.parametrize(
    "change",
    [
        {"after_head": "c" * 40},
        {"after_base": "c" * 40},
        {"after_count": 2},
    ],
)
def test_head_base_or_count_race_refuses_skip(change):
    with pytest.raises(ValueError, match="PR changed"):
        collect(API(1, [[file("docs/a.md")]], **change))


def test_stale_event_sha_refuses_skip():
    with pytest.raises(ValueError, match="head changed"):
        paths.changed_files(API(1, []), 365, "c" * 40, BASE)
    with pytest.raises(ValueError, match="base changed"):
        paths.changed_files(API(1, []), 365, HEAD, "c" * 40)


def test_reusable_classifier_is_inline_no_checkout_and_matches_reviewed_helper():
    workflow = (ROOT / ".github/workflows/ci-changed-paths.yml").read_text()
    embedded = workflow.split("          # BEGIN CI_CHANGED_PATHS\n", 1)[1].split(
        "          # END CI_CHANGED_PATHS\n", 1
    )[0]
    assert textwrap.dedent(embedded) == (ROOT / "scripts/ci_changed_paths.py").read_text()
    assert "checkout" not in workflow.lower().replace("no checkout", "")
    assert "${{ secrets." not in workflow
    assert "workflow_call:" in workflow
    assert "value: ${{ jobs.classify.outputs.run_full }}" in workflow


def test_all_required_jobs_report_and_fall_back_to_full_on_classifier_failure():
    guard = "if: ${{ always() && !cancelled() && (needs.changes.result != 'success' || needs.changes.outputs.run_full != 'false') }}"
    for name, jobs in [("tests.yml", ["lint", "pytest", "frontend"]), ("e2e.yml", ["e2e"])]:
        workflow = (ROOT / ".github/workflows" / name).read_text()
        assert "on:\n  pull_request:\n" in workflow
        assert "    paths:" not in workflow
        assert "uses: ./.github/workflows/ci-changed-paths.yml" in workflow
        for job in jobs:
            assert f"  {job}:\n    needs: changes\n    {guard}\n" in workflow
    checks = (ROOT / ".github/workflows/tests.yml").read_text()
    for check_name in ("ruff", "pytest", "frontend build"):
        assert f"    name: {check_name}\n" in checks


def test_thirty_full_pages_refuse_completeness():
    docs = [file(f"docs/{n}.md") for n in range(100)]
    with pytest.raises(ValueError, match="pagination limit"):
        collect(API(2999, [docs] * 30))


@pytest.mark.parametrize("batch", [{"message": "API error"}, [file("docs/a.md")] * 101])
def test_invalid_page_shape_refuses_skip(batch):
    with pytest.raises(ValueError, match="invalid PR-files"):
        collect(API(1, [batch]))
