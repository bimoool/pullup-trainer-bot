"""Native Codex review acceptance, using authentic REST bot identity and state schema."""

import copy
import importlib.util
import json
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "codex_review_gate", ROOT / "scripts/codex_review_gate.py"
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
REPO = "bimoool/pullup-trainer-bot"
SHA = "a" * 40


def summary(*, sha=SHA, status="completed", any_findings=False, unresolved=False, comment_id=100):
    return {
        "id": comment_id,
        "user": {"id": 199175422, "login": "chatgpt-codex-connector[bot]", "type": "Bot"},
        "issue_url": f"https://api.github.com/repos/{REPO}/issues/365",
        "body": gate.SUMMARY
        + "\n<!-- codex-review-state:v1 "
        + json.dumps(
            {
                "code_review": {
                    "commit_sha": sha,
                    "status": status,
                    "has_any_findings": any_findings,
                    "has_unresolved_findings": unresolved,
                },
                "security_review": {"commit_sha": None, "status": None},
            }
        )
        + " -->\n\nHuman-readable summary is not an acceptance signal.",
    }


def state(comments):
    return gate.review_state(comments, REPO, 365, SHA)


def test_current_completed_review_is_accepted():
    assert state([summary()]) == "accepted"


def test_resolved_findings_are_accepted():
    assert state([summary(any_findings=True, unresolved=False)]) == "accepted"


@pytest.mark.parametrize("status", ["running", "pending", "queued", None])
def test_pending_never_accepted(status):
    assert state([summary(status=status)]) != "accepted"


def test_wrong_sha_never_accepted():
    assert state([summary(sha="b" * 40)]) != "accepted"


@pytest.mark.parametrize("status", ["error", "failed", "cancelled", "success", "done", "unknown"])
def test_unconfirmed_terminal_status_fails_closed(status):
    with pytest.raises(gate.GateError):
        state([summary(status=status)])


def test_unresolved_findings_refused():
    with pytest.raises(gate.GateError, match="unresolved"):
        state([summary(any_findings=True, unresolved=True)])


@pytest.mark.parametrize("flag", [None, 0, 1, "false", [], {}])
def test_unknown_flags_refused(flag):
    with pytest.raises(gate.GateError, match="unknown findings"):
        state([summary(unresolved=flag)])
    with pytest.raises(gate.GateError, match="unknown findings"):
        state([summary(any_findings=flag)])


@pytest.mark.parametrize(
    "key,value",
    [
        ("id", 123),
        ("login", "lookalike[bot]"),
        ("type", "User"),
    ],
)
def test_spoofed_author_never_accepted(key, value):
    comment = summary()
    comment["user"][key] = value
    assert state([comment]) != "accepted"


def test_wrong_pr_or_repository_never_accepted():
    comment = summary()
    comment["issue_url"] += "0"
    assert state([comment]) != "accepted"


def test_latest_authentic_summary_cannot_be_overridden_by_old_success():
    assert state([summary(comment_id=10), summary(status="running", comment_id=11)]) != "accepted"
    assert state([summary(comment_id=10), summary(sha="b" * 40, comment_id=11)]) != "accepted"


def test_untrusted_newer_comment_cannot_override_authentic_state():
    fake = summary(comment_id=999)
    fake["user"]["id"] = 123
    assert state([summary(status="running"), fake]) != "accepted"


def test_human_friendly_success_text_not_sufficient():
    comment = summary()
    comment["body"] = "Codex approved this PR. All checks succeeded."
    assert state([comment]) != "accepted"


@pytest.mark.parametrize(
    "body",
    [
        gate.SUMMARY + "\n<!-- codex-review-state:v2 {} -->",
        gate.SUMMARY + "\n<!-- codex-review-state:v1 invalid -->",
        gate.SUMMARY + '\n<!-- codex-review-state:v1 {"code_review":{},"code_review":{}} -->',
    ],
)
def test_malformed_or_changed_schema_refused(body):
    comment = summary()
    comment["body"] = body
    with pytest.raises(gate.GateError):
        state([comment])


def test_duplicate_state_markers_refused():
    comment = summary()
    comment["body"] += "\n" + comment["body"].splitlines()[1]
    with pytest.raises(gate.GateError):
        state([comment])


class API:
    def __init__(self, heads, comments):
        self.heads = iter(heads)
        self.reviews = comments

    def head(self, number):
        return next(self.heads)

    def comments(self, number):
        return copy.deepcopy(self.reviews)


def test_head_race_invalidates_completed_review():
    with pytest.raises(gate.GateError, match="head changed"):
        gate.wait_for_review(API([SHA, "b" * 40], [summary()]), REPO, 365, SHA)


def test_superseded_job_refuses_immediately():
    with pytest.raises(gate.GateError, match="superseded"):
        gate.wait_for_review(API(["b" * 40], []), REPO, 365, SHA)


def test_pending_is_bounded_and_never_turns_green(monkeypatch):
    monkeypatch.setattr(gate, "WAIT_SECONDS", 1)
    clock_values = iter([0, 2])
    with pytest.raises(gate.GateError, match="timed out"):
        gate.wait_for_review(API([SHA], []), REPO, 365, SHA, clock=lambda: next(clock_values))


def test_workflow_runs_exact_reviewed_gate_without_checkout_or_secrets():
    workflow = (ROOT / ".github/workflows/claude-code-review.yml").read_text()
    embedded = workflow.split("          # BEGIN CODEX_REVIEW_GATE\n", 1)[1].split(
        "          # END CODEX_REVIEW_GATE\n", 1
    )[0]
    assert textwrap.dedent(embedded) == (ROOT / "scripts/codex_review_gate.py").read_text()
    assert "actions/checkout" not in workflow
    assert "${{ secrets." not in workflow
    assert "contents: write" not in workflow
    assert "timeout-minutes: 15" in workflow
    legacy = (ROOT / ".github/workflows/claude-code-review-manual.yml").read_text()
    assert "workflow_dispatch:" in legacy
    assert "pull_request:" not in legacy
