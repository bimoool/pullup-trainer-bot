"""ORCH-1 orchestrator: pure rules + a full planner → worker → planner simulation.

No database, no network: `scripts/orch.py` is stdlib-only, and the simulation drives the real
command handlers (`cmd_plan`, `cmd_worker_guard`, `cmd_worker_record`) against an in-memory fake
GitHub, with the orchestration files written to a temp dir.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "orch", Path(__file__).resolve().parent.parent / "scripts" / "orch.py"
)
orch = importlib.util.module_from_spec(_SPEC)
sys.modules["orch"] = orch
_SPEC.loader.exec_module(orch)

GOOD_BODY = """## Goal
Make the widget show the right total.

## Why
Users see wrong numbers.

## Acceptance criteria
- [ ] total equals sum of sets
- [ ] regression test fails without the fix

## Out of scope
Deploying to production; merging main.

## Tests
pytest tests/test_widget.py

## Owner decision required?
no
"""


def body(goal: str = "Make the widget show the right total.", decision: str = "no") -> str:
    return GOOD_BODY.replace("Make the widget show the right total.", goal).replace(
        "required?\nno", f"required?\n{decision}"
    )


def issue(n, labels=(), b=GOOD_BODY, title=None, author="owner", state="OPEN"):
    return orch.Issue(
        number=n,
        title=title or f"task {n}",
        body=b,
        labels=set(labels),
        state=state,
        author=author,
        url=f"https://example.test/issues/{n}",
    )


class FakeGh:
    def __init__(self, issues):
        self.issues = {i.number: i for i in issues}
        self.comments: dict[int, list[str]] = {}
        self.dashboard_body = None

    def list_issues(self):
        return [orch.Issue(**{**vars(i), "labels": set(i.labels)}) for i in self.issues.values()]

    def get_issue(self, n):
        i = self.issues[n]
        return orch.Issue(**{**vars(i), "labels": set(i.labels)})

    def set_status(self, n, status, current):
        i = self.issues[n]
        i.labels = (i.labels - set(orch.STATUS_LABELS)) | {status}

    def comment(self, n, text):
        self.comments.setdefault(n, []).append(text)

    def close(self, n):
        self.issues[n].state = "CLOSED"
        self.issues[n].state_reason = "COMPLETED"
        self.issues[n].closed_at = f"2026-09-29T12:{n % 60:02d}:00Z"

    def set_body(self, n, text):
        self.dashboard_body = text

    def pr(self, n):
        return {"state": "OPEN", "isDraft": True, "checks": "green"}

    def last_run(self, workflow):
        return None


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Temp 'checkout' holding the orchestration files; git/network status bits stubbed."""
    monkeypatch.setattr(orch, "ROOT", tmp_path)
    state = orch.default_state()
    state.update(
        canonical_pr=226, phase="test phase", trusted_authors=["owner"], dashboard_issue=99
    )
    (tmp_path / ".github/orch").mkdir(parents=True)
    (tmp_path / ".github/task").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    orch.save_state(state)
    orch.write(orch.BRIEF_PATH, orch.render_idle_brief("init"))

    def fake_gather(gh, st, issues=None):
        return orch.StatusContext(
            now="2026-09-29 12:00 UTC",
            state=st,
            issues=issues if issues is not None else gh.list_issues(),
            code_sha="c0ffee" * 7,
            pr=gh.pr(226),
            brief_text=orch.read(orch.BRIEF_PATH),
            staging="ok",
            production="untouched",
        )

    monkeypatch.setattr(orch, "gather_status", fake_gather)
    monkeypatch.setattr(orch, "run", lambda cmd, check=True, cwd=None: "b" * 40 + "\n")
    monkeypatch.setattr(orch, "remote_branch_sha", lambda branch: None)
    return tmp_path


def ns(**kw):
    base = {"apply": False, "publish": True, "push": False}
    base.update(kw)
    return argparse.Namespace(**base)


def record_args(n, **kw):
    base = {
        "issue": n,
        "verdict": "done",
        "result_file": None,
        "tests_ok": "1",
        "tests_summary": "ruff ok, pytest ok",
        "commits_ahead": 2,
        "forbidden": "",
        "merged": "1",
        "sha": "d" * 40,
        "run_url": "",
        "publish": True,
        "push": False,
    }
    base.update(kw)
    return argparse.Namespace(**base)


# --------------------------------------------------------------------------- pure rules


def test_template_body_is_ready():
    tpl = (
        Path(__file__).resolve().parent.parent / ".github/ISSUE_TEMPLATE/implementation.md"
    ).read_text()
    filled = tpl.split("---", 2)[2].replace("- [ ] <!-- checkable, observable -->", "- [ ] x works")
    assert orch.check_ready(issue(1, b=filled), ["owner"]).ok


@pytest.mark.parametrize(
    ("b", "reason"),
    [
        (GOOD_BODY.replace("## Acceptance criteria", "## Notes"), "missing section"),
        (
            GOOD_BODY.replace(
                "- [ ] total equals sum of sets\n- [ ] regression test fails without the fix", "tbd"
            ),
            "no checkable",
        ),
        (body(decision="yes: which icon set"), "not 'no'"),
        (body(goal="Deploy to production after merge"), "production deploy"),
        (body(goal="Verify the timer on a real iPhone"), "real-device"),
        (body(goal="Drop column users.legacy_score"), "destructive migration"),
        (body(goal="Rotate the bot secret"), "credentials"),
        (body(goal="Изменить формулу прогрессии"), "progression"),
    ],
)
def test_not_ready_goes_to_needs_owner(b, reason):
    r = orch.check_ready(issue(1, b=b), ["owner"])
    assert not r.ok and r.label == "status:needs-owner" and reason in r.reason


def test_out_of_scope_mentions_do_not_trip_stop_conditions():
    # GOOD_BODY's Out of scope says "Deploying to production; merging main" — must stay ready.
    assert orch.check_ready(issue(1), ["owner"]).ok


def test_untrusted_author_needs_owner_approval():
    assert not orch.check_ready(issue(1, author="stranger"), ["owner"]).ok
    assert orch.check_ready(
        issue(1, author="stranger", labels=["orch:owner-approved"]), ["owner"]
    ).ok


def test_owner_approved_clears_stop_tripwire():
    i = issue(1, b=body(goal="Check iPhone safe-area CSS in e2e"), labels=["orch:owner-approved"])
    assert orch.check_ready(i, ["owner"]).ok


def test_invariants():
    v = orch.find_violations(
        [
            issue(1, ["status:ready", "status:in-progress"]),
            issue(2, ["status:in-progress", "status:done"]),
            issue(3, ["status:done"]),
            issue(4, ["status:in-progress"], state="CLOSED"),
        ]
    )
    text = "\n".join(v)
    assert (
        "#1 has 2" in text
        and "#2 has 2" in text
        and "#3 is open" in text
        and "#4 is closed" in text
    )
    assert "more than one open status:in-progress" in text


def test_queue_order_priority_then_bug_then_age():
    issues = [
        issue(5, ["status:ready", "priority:p2"]),
        issue(4, ["status:ready", "priority:p1", "type:feature"]),
        issue(9, ["status:ready", "priority:p1", "type:bug"]),
        issue(2, ["status:ready"]),
        issue(3, ["status:ready", "priority:p0"]),
        issue(1, ["status:ready", "orch:test"]),
        issue(7, ["status:needs-owner", "priority:p0"]),
    ]
    assert [i.number for i in orch.ready_queue(issues, orch.default_state())] == [3, 9, 4, 5, 2]
    sandbox = {**orch.default_state(), "scope_label": "orch:test"}
    assert [i.number for i in orch.ready_queue(issues, sandbox)] == [1]


def test_final_verdict_gate_never_trusts_agent_alone():
    assert orch.final_verdict("done", True, 2, [], True)[0] == "done"
    assert orch.final_verdict("done", False, 2, [], True)[0] == "blocked"
    assert orch.final_verdict("done", True, 0, [], True)[0] == "blocked"
    assert orch.final_verdict("done", True, 2, [], False)[0] == "blocked"
    assert (
        orch.final_verdict("done", True, 2, [".github/workflows/x.yml"], True)[0] == "needs-owner"
    )
    assert orch.final_verdict("needs-owner", True, 2, [], None)[0] == "needs-owner"


def test_forbidden_changes():
    assert orch.forbidden_changes(["app/x.py"], "+ op.add_column('t', c)") == []
    assert orch.forbidden_changes([".github/orch/state.json", "docs/PROJECT_STATUS.md"], "")
    assert orch.forbidden_changes(["alembic/versions/x.py"], "+    op.drop_column('users', 'x')")


def test_base_guard_never_main():
    st = orch.default_state()
    i = issue(1, ["status:in-progress"])
    brief = "ISSUE: #1\n"
    st["batch"]["status"] = "running"
    assert "not an allowed" in orch.worker_guard(i, st, brief, "main")
    assert orch.worker_guard(i, st, brief, "develop/current") is None


def test_parse_result_defaults_to_blocked():
    assert orch.parse_result("VERDICT: done\nSUMMARY: x")["verdict"] == "done"
    assert orch.parse_result("I think it's finished")["verdict"] == "blocked"


# --------------------------------------------------------------------------- simulation


def test_full_loop_simulation(repo):
    """ORCH-E dry run: select → in-progress → no duplicate → done → counter → 5/5 stop."""
    issues = [
        issue(99, ["orch:dashboard"], title="Project Status"),
        issue(
            102, ["status:ready", "priority:p0"], b=body(goal="Check the timer on a real iPhone")
        ),
        issue(101, ["status:ready", "priority:p1", "type:bug"]),
        issue(103, ["status:ready", "priority:p1"], b="just do it"),
        issue(104, ["status:needs-owner", "priority:p0"]),
        issue(105, ["status:blocked", "priority:p0"]),
        *[issue(n, ["status:ready", "priority:p2"]) for n in range(110, 117)],
    ]
    gh = FakeGh(issues)

    # 0. No batch approved → planner never starts anything, even with --apply.
    orch.cmd_plan(ns(apply=True), gh)
    assert not any("status:in-progress" in i.labels for i in gh.issues.values())
    assert orch.load_state()["batch"]["status"] == "idle"
    # …but it did normalize: vague #103 and iPhone #102 are now needs-owner, with a reason.
    assert gh.issues[102].labels == {"status:needs-owner", "priority:p0"}
    assert gh.issues[103].labels == {"status:needs-owner", "priority:p1"}
    assert "real-device" in gh.comments[102][-1]

    # Owner starts batch 1.
    state = orch.load_state()
    orch.batch_start(state, by="owner", now="t0")
    orch.save_state(state)

    completed = []
    for round_ in range(1, 6):
        orch.cmd_plan(ns(apply=True), gh)
        active = [i for i in gh.issues.values() if "status:in-progress" in i.labels]
        assert len(active) == 1, "exactly one task in progress"
        n = active[0].number
        # needs-owner / blocked issues are never selected
        assert n not in (102, 103, 104, 105)
        if round_ == 1:
            assert n == 101  # p1 bug beats p2; p0 #102 was rejected
        brief = orch.read(orch.BRIEF_PATH)
        assert f"ISSUE: #{n}" in brief and f"BRANCH: orch/issue-{n}" in brief
        status = orch.read(orch.STATUS_PATH)
        assert "## IN PROGRESS" in status and f"#{n}]" in status.split("## READY NEXT")[0]
        assert gh.dashboard_body and f"#{n}]" in gh.dashboard_body

        # Duplicate planner run: no second worker, nothing relabelled.
        before = {k: set(v.labels) for k, v in gh.issues.items()}
        orch.cmd_plan(ns(apply=True), gh)
        assert {k: set(v.labels) for k, v in gh.issues.items()} == before
        assert orch.plan(gh.list_issues(), orch.load_state()).action == "active-exists"

        # Worker guard: only the brief's issue may run.
        assert orch.cmd_worker_guard(argparse.Namespace(issue=n, base="develop/current"), gh) == 0
        other = next(i for i in gh.issues.values() if "status:ready" in i.labels)
        assert (
            orch.cmd_worker_guard(
                argparse.Namespace(issue=other.number, base="develop/current"), gh
            )
            == 1
        )
        assert orch.cmd_worker_guard(argparse.Namespace(issue=n, base="main"), gh) == 1

        orch.cmd_worker_record(record_args(n), gh)
        completed.append(n)
        assert gh.issues[n].state == "CLOSED" and gh.issues[n].labels & {"status:done"}
        st = orch.load_state()
        assert st["batch"]["completed"] == completed
        assert orch.brief_issue(orch.read(orch.BRIEF_PATH)) is None
        assert f"{len(completed)}/5" in orch.read(orch.STATUS_PATH)

    # 5/5: batch is in owner review, no sixth task starts although ready issues remain.
    st = orch.load_state()
    assert st["batch"]["status"] == "owner-review"
    remaining_ready = [
        i.number for i in gh.issues.values() if "status:ready" in i.labels and i.is_open
    ]
    assert remaining_ready, "there IS still work — the limit, not an empty queue, stops the loop"
    orch.cmd_plan(ns(apply=True), gh)
    assert not any("status:in-progress" in i.labels for i in gh.issues.values())
    status = orch.read(orch.STATUS_PATH)
    assert "AUTONOMOUS BATCH 1: 5/5 — STOP — OWNER REVIEW REQUIRED" in status
    assert orch.batch_can_start(orch.load_state())[0] is False
    # Recently done shows the five completions.
    done_part = status.split("## RECENTLY DONE")[1].split("##")[0]
    assert all(f"#{n}]" in done_part for n in completed)
    # Owner can start the next batch explicitly.
    st = orch.load_state()
    orch.batch_start(st, by="owner", now="t1")
    assert st["batch"]["id"] == 2 and st["batch"]["completed"] == []


def test_failed_worker_does_not_count_and_attempts_cap(repo):
    gh = FakeGh([issue(n, ["status:ready", "priority:p1"]) for n in range(1, 12)])
    st = orch.load_state()
    orch.batch_start(st, by="owner", now="t0")
    orch.save_state(st)
    for _ in range(8):
        orch.cmd_plan(ns(apply=True), gh)
        n = next(i.number for i in gh.issues.values() if "status:in-progress" in i.labels)
        orch.cmd_worker_record(record_args(n, tests_ok="0"), gh)  # agent says done, CI red
        assert gh.issues[n].labels == {"status:blocked", "priority:p1"}
        assert gh.issues[n].state == "OPEN"
    st = orch.load_state()
    assert st["batch"]["completed"] == [] and len(st["batch"]["attempts"]) == 8
    assert st["batch"]["status"] == "owner-review"
    orch.cmd_plan(ns(apply=True), gh)
    assert not any("status:in-progress" in i.labels for i in gh.issues.values())


def test_status_page_is_short_and_complete(repo):
    gh = FakeGh(
        [
            issue(1, ["status:ready", "priority:p1"]),
            issue(2, ["status:needs-owner"]),
            issue(3, ["status:blocked"]),
            issue(4, ["status:done"], state="CLOSED"),
        ]
    )
    gh.issues[4].closed_at = "2026-09-29T00:00:00Z"
    text = orch.refresh_status(gh, orch.load_state(), publish=False)
    for heading in (
        "# Project Status",
        "## Canonical",
        "## Current phase",
        "## IN PROGRESS",
        "## READY NEXT",
        "## BLOCKED",
        "## NEEDS OWNER",
        "## RECENTLY DONE",
        "## AUTONOMOUS BATCH",
        "## ENVIRONMENTS",
    ):
        assert heading in text
    assert len(text.splitlines()) < 150
    assert json.loads((repo / orch.STATE_PATH).read_text())["canonical_branch"] == "develop/current"
