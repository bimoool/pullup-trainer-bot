#!/usr/bin/env python3
"""Owner-comment bridge. No comment text is evaluated or used as shell arguments."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from types import SimpleNamespace

import orch

REPO = "bimoool/pullup-trainer-bot"
OWNER = "bimoool"
DASHBOARD = 230
SANDBOX = "orch-sandbox/orch2-ui-proof"
COMMANDS = {
    "/orch start": ("start", "develop/current"),
    "/orch stop": ("stop", "develop/current"),
    "/orch approve": ("approve", "develop/current"),
    "/orch sandbox-start": ("start", SANDBOX),
    "/orch sandbox-stop": ("stop", SANDBOX),
}


def authorize(comment: dict, issue: dict, base: str, now: dt.datetime) -> str:
    if comment.get("user", {}).get("login") != OWNER:
        raise ValueError("only the repository owner may issue commands")
    if comment.get("created_at") != comment.get("updated_at"):
        raise ValueError("edited comments are not commands; post a new comment")
    created = dt.datetime.fromisoformat(comment["created_at"].replace("Z", "+00:00"))
    if not 0 <= (now - created).total_seconds() <= 3600:
        raise ValueError("command expired; post a new comment")
    command, target = COMMANDS.get(comment.get("body", "").strip(), (None, None))
    if not command or target != base:
        raise ValueError("unknown command or forbidden target")
    if "pull_request" in issue or issue.get("state") != "open":
        raise ValueError("commands require an open issue, not a pull request")
    expected = f"https://api.github.com/repos/{REPO}/issues/{issue['number']}"
    if comment.get("issue_url") != expected:
        raise ValueError("comment belongs to another issue/repository")
    if command == "approve":
        labels = {x["name"] for x in issue.get("labels", [])}
        if issue["number"] == DASHBOARD or labels & {"orch:test", "orch:dashboard", "status:in-progress", "status:done"}:
            raise ValueError("cannot approve dashboard, sandbox, active or completed issue")
    elif issue["number"] != DASHBOARD:
        raise ValueError("start/stop commands belong on dashboard #230")
    return command


def transition(state: dict, command: str, comment_id: int, active: bool) -> bool:
    """Replay-safe batch transition. Busy starts never reset counters or start a new batch."""
    if comment_id <= state.get("last_owner_comment_id", 0):
        return False
    if state["canonical_branch"] not in ("develop/current", SANDBOX):
        raise ValueError("forbidden state branch")
    b = state["batch"]
    if not 1 <= b["limit"] <= 5 or not 1 <= b["max_attempts"] <= 8:
        raise ValueError("batch limits exceed ORCH safety caps")
    if command == "stop":
        orch.batch_stop(state)
    elif b["status"] != "running" and not active:
        orch.batch_start(state, OWNER, orch.utcnow())
    state["last_owner_comment_id"] = comment_id
    return True


def api(path: str) -> dict:
    return json.loads(orch.run(["gh", "api", f"repos/{REPO}/{path}"]))


def pause_label(base: str) -> str:
    if base not in ("develop/current", SANDBOX):
        # Existing ORCH-1 sandbox branches are not controlled by this bridge.
        return ""
    return "orch:paused" if base == "develop/current" else "orch:sandbox-paused"


def paused(base: str) -> bool:
    label = pause_label(base)
    return bool(label and label in {x["name"] for x in api(f"issues/{DASHBOARD}")["labels"]})


def apply_owner_event(comment_id: str, base: str) -> None:
    if os.environ.get("GITHUB_REPOSITORY") != REPO or not re.fullmatch(r"[0-9]{1,20}", comment_id):
        raise ValueError("invalid repository/comment id")
    comment = api(f"issues/comments/{comment_id}")
    match = re.fullmatch(rf"https://api.github.com/repos/{REPO}/issues/([0-9]+)", comment.get("issue_url", ""))
    if not match:
        raise ValueError("foreign issue")
    raw_issue = api(f"issues/{match[1]}")
    command = authorize(comment, raw_issue, base, dt.datetime.now(dt.UTC))
    state = orch.load_state()
    if state["canonical_branch"] != base:
        raise ValueError("checkout/state/command target mismatch")
    if base == SANDBOX and (state.get("scope_label") != "orch:ui-proof" or state["batch"]["limit"] != 1):
        raise ValueError("sandbox must be isolated and limited to one task")
    gh = orch.Gh()
    active = bool(orch.active_issues(gh.list_issues(), state))
    if not transition(state, command, int(comment_id), active):
        print("Already handled or superseded; no changes")
        return
    if command == "approve":
        issue = gh.get_issue(raw_issue["number"])
        issue.labels.add(orch.OWNER_APPROVED_LABEL)
        ready = orch.check_ready(issue, state.get("trusted_authors") or [])
        if not ready.ok:
            raise ValueError(f"issue not executable: {ready.reason}")
        orch.run(["gh", "issue", "edit", str(issue.number), "--add-label", orch.OWNER_APPROVED_LABEL])
        gh.set_status(issue.number, "status:ready", issue.labels)
    label = pause_label(base)
    if command == "stop":
        orch.run(["gh", "label", "create", label, "--color", "d93f0b", "--description", "Owner paused ORCH task selection", "--force"])
        orch.run(["gh", "issue", "edit", str(DASHBOARD), "--add-label", label])
    elif state["batch"]["status"] == "running":
        orch.run(["gh", "issue", "edit", str(DASHBOARD), "--remove-label", label])
    orch.save_state(state)
    orch.refresh_status(gh, state, publish=True)
    orch.commit_and_push([orch.STATE_PATH, orch.STATUS_PATH], f"owner {command} (comment {comment_id})", base)
    run_url = f"https://github.com/{REPO}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    gh.comment(DASHBOARD, f"🕹️ Owner command **{command}** applied to `{base}`. [Request]({comment['html_url']}) · [Planner]({run_url})\n\n{orch.batch_line(state)}\n\n" + ("Graceful stop: any in-flight worker may finish; no next task starts." if command == "stop" else "Planner checks the existing queue and safety gates; running batch counters are preserved."))
    if command != "stop" and not paused(base):
        orch.cmd_plan(SimpleNamespace(apply=True, publish=True, push=True), gh)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["event", "pause-check"])
    p.add_argument("--comment-id", default="")
    p.add_argument("--base", required=True)
    a = p.parse_args()
    if a.mode == "event":
        apply_owner_event(a.comment_id, a.base)
    elif paused(a.base):
        raise SystemExit("Owner pause is active; no new task may start")


if __name__ == "__main__":
    main()
