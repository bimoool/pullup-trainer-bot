#!/usr/bin/env python3
"""ORCH-1 — cross-device issue orchestrator (planner core, batch accounting, status page).

Single stdlib-only module, no project imports: runs from any clone with `gh auth`, and from
GitHub Actions. Pure decision logic (plan / validate / batch / render) is separated from I/O
(`Gh`, git) so tests/test_orch.py can drive the whole loop against a fake GitHub.

Rules this code enforces are specified in docs/PLANNER_AGENT.md, docs/WORKER_AGENT.md and
docs/AGENT_EXECUTION_MODEL.md ("Orchestration" section). State lives ONLY in GitHub (labels,
comments) and in files on the canonical branch (.github/orch/state.json,
.github/task/current.md, docs/PROJECT_STATUS.md) — never on a local disk or in a chat.

Usage (from the repo root):
    python scripts/orch.py where                 # "where are we?" — print status, write nothing
    python scripts/orch.py status [--publish]    # refresh docs/PROJECT_STATUS.md (+ dashboard issue)
    python scripts/orch.py plan                  # planner DRY RUN: what would be selected and why
    python scripts/orch.py plan --apply          # planner: label, brief, state, status (batch must run)
    python scripts/orch.py batch show|start|stop # batch accounting (start/stop = owner only)
    python scripts/orch.py check                 # label/state invariants
    python scripts/orch.py resume                # how to continue the active task on this machine
    python scripts/orch.py checkpoint --issue N --note "..."   # worker checkpoint comment + status
    python scripts/orch.py worker-guard --issue N              # used by orch-worker.yml
    python scripts/orch.py worker-record --issue N --verdict done|blocked|needs-owner ...
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ".github/orch/state.json"
BRIEF_PATH = ".github/task/current.md"
STATUS_PATH = "docs/PROJECT_STATUS.md"
ORCH_COMMIT_PREFIX = "chore(orch):"

STATUS_LABELS = (
    "status:backlog",
    "status:ready",
    "status:in-progress",
    "status:blocked",
    "status:needs-owner",
    "status:done",
)
PRIORITY_RANK = {"priority:p0": 0, "priority:p1": 1, "priority:p2": 2}
DASHBOARD_LABEL = "orch:dashboard"
TEST_LABEL = "orch:test"
OWNER_APPROVED_LABEL = "orch:owner-approved"

# Base branches the automation may ever write to. `main` is deliberately impossible.
ALLOWED_BASE_RE = re.compile(r"^(develop/current|orch-sandbox/[A-Za-z0-9._-]+)$")

# Paths a worker must never change: orchestration state is written only by the planner /
# finish step, and GITHUB_TOKEN cannot push workflow files anyway.
WORKER_FORBIDDEN_PREFIXES = (
    ".github/workflows/",
    ".github/orch/",
    ".github/task/",
    STATUS_PATH,
)
DESTRUCTIVE_MIGRATION_RE = re.compile(
    r"op\.drop_(table|column|index|constraint)|\bTRUNCATE\b|\bDELETE\s+FROM\b", re.IGNORECASE
)

# Owner stop conditions (docs/PLANNER_AGENT.md §Owner stop conditions). Scanned in the title,
# Goal and Acceptance-criteria sections only — "Out of scope: no prod deploy" must not trip it.
# A false positive is cleared by the owner adding `orch:owner-approved`.
OWNER_STOP_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "production deploy",
        r"\bprod(uction)?\b[^.\n]{0,40}\bdeploy|\bdeploy[^.\n]{0,40}\bprod(uction)?\b|деплой[^.\n]{0,30}прод|прод[^.\n]{0,30}деплой",
    ),
    ("merge to main", r"\bmerge[^.\n]{0,20}\bmain\b|\bв main\b"),
    (
        "destructive migration",
        r"\bdrop (table|column)\b|destructive migration|\btruncate\b|удал\w* (таблиц|колонк|столбц)",
    ),
    ("credentials / secrets", r"\bcredential|\bsecret|\bpassword|\bapi[ _-]?key|парол|секрет"),
    (
        "paid external service",
        r"\bpurchase\b|\bbuy\b|\bpaid (service|plan|tier)|\bbilling\b|купить|оплатить сервис",
    ),
    (
        "irreversible data operation",
        r"irreversib|\bwipe\b|hard[- ]delete (user|history|all)|delete (all|user|users|history)|удал\w* (пользовател|истори|все)",
    ),
    (
        "security policy decision",
        r"security[- ]policy|auth(entication)? policy|политик\w* безопасност",
    ),
    (
        "core progression semantics",
        r"progression (formula|semantics|rule)|формул\w* прогресси|семантик\w* прогресси",
    ),
    ("reference data deletion", r"delete[^.\n]{0,20}reference data|удал\w*[^.\n]{0,20}справочн"),
    (
        "real-device manual validation",
        r"\biphone\b|\breal device\b|\bon[- ]device\b|реальн\w* (устройств|телефон|iphone)",
    ),
)

REQUIRED_SECTIONS = ("goal", "acceptance criteria", "tests", "owner decision required")

DEFAULT_DO_NOT_TOUCH = (
    "`main` — never merge, never push",
    "production deploy (`deploy.yml`) — never run",
    "`.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`",
    "destructive / non-additive Alembic migrations",
    "secrets, tokens, `.env*`",
    "other issues' scope — no drive-by features",
)
DEFAULT_STOP_CONDITIONS = (
    "acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner",
    "task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner",
    "tests cannot be made green within scope → VERDICT blocked (push what exists, explain)",
    "scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal",
)


# --------------------------------------------------------------------------- data model


@dataclasses.dataclass
class Issue:
    number: int
    title: str
    body: str = ""
    labels: set[str] = dataclasses.field(default_factory=set)
    state: str = "OPEN"  # OPEN | CLOSED
    state_reason: str | None = None
    closed_at: str | None = None
    author: str = ""
    url: str = ""

    @property
    def is_open(self) -> bool:
        return self.state.upper() == "OPEN"

    @property
    def status(self) -> list[str]:
        return sorted(lbl for lbl in self.labels if lbl in STATUS_LABELS)

    @property
    def priority(self) -> str | None:
        for lbl in PRIORITY_RANK:
            if lbl in self.labels:
                return lbl
        return None

    @property
    def type(self) -> str | None:
        return next((lbl for lbl in sorted(self.labels) if lbl.startswith("type:")), None)

    @classmethod
    def from_gh(cls, d: dict) -> Issue:
        return cls(
            number=d["number"],
            title=d.get("title", ""),
            body=d.get("body") or "",
            labels={lbl["name"] for lbl in d.get("labels", [])},
            state=d.get("state", "OPEN"),
            state_reason=d.get("stateReason"),
            closed_at=d.get("closedAt"),
            author=(d.get("author") or {}).get("login", ""),
            url=d.get("url", ""),
        )


def default_state() -> dict:
    return {
        "canonical_branch": "develop/current",
        "canonical_pr": None,
        "phase": "",
        "trusted_authors": [],
        "scope_label": None,  # sandbox runs set "orch:test"; canonical excludes orch:test
        "dashboard_issue": None,
        "owner_notes": [],
        "batch": {
            "id": 0,
            "limit": 5,
            "max_attempts": 8,
            "status": "idle",  # idle | running | owner-review | stopped
            "approved_by": None,
            "started_at": None,
            "completed": [],
            "attempts": [],
        },
    }


# --------------------------------------------------------------------------- issue parsing


_HEADING_RE = re.compile(r"^#{2,4}\s+(.+?)\s*$", re.MULTILINE)


def parse_sections(body: str) -> dict[str, str]:
    """`## Heading` → text. Keys are lower-cased, trailing '?' / ':' stripped. Works for both
    hand-written bodies and GitHub issue-form output (`### Heading`)."""
    sections: dict[str, str] = {}
    matches = list(_HEADING_RE.finditer(body or ""))
    for i, m in enumerate(matches):
        key = m.group(1).strip().lower().rstrip("?:").strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[key] = body[m.end() : end].strip()
    return sections


def section(sections: dict[str, str], name: str) -> str | None:
    for key, text in sections.items():
        if key.startswith(name):
            return text
    return None


def _has_list_item(text: str) -> bool:
    return bool(re.search(r"^\s*([-*]|\d+[.)])\s+\S", text or "", re.MULTILINE))


def owner_stop_reasons(issue: Issue) -> list[str]:
    sections = parse_sections(issue.body)
    scanned = "\n".join(
        [
            issue.title,
            section(sections, "goal") or "",
            section(sections, "acceptance criteria") or "",
        ]
    ).lower()
    return [name for name, pattern in OWNER_STOP_PATTERNS if re.search(pattern, scanned)]


@dataclasses.dataclass
class Readiness:
    ok: bool
    label: str | None = None  # label to move a rejected issue to
    reason: str = ""


def check_ready(issue: Issue, trusted_authors: list[str]) -> Readiness:
    """Is this `status:ready` issue safe and specific enough to hand to a worker?"""
    if (
        trusted_authors
        and issue.author not in trusted_authors
        and OWNER_APPROVED_LABEL not in issue.labels
    ):
        return Readiness(
            False,
            "status:needs-owner",
            f"author @{issue.author} is not trusted; owner must add `{OWNER_APPROVED_LABEL}`",
        )
    sections = parse_sections(issue.body)
    missing = [s for s in REQUIRED_SECTIONS if section(sections, s) is None]
    if missing:
        return Readiness(
            False,
            "status:needs-owner",
            "missing section(s): " + ", ".join(missing) + " (use the Implementation task template)",
        )
    if not _has_list_item(section(sections, "acceptance criteria") or ""):
        return Readiness(
            False, "status:needs-owner", "acceptance criteria have no checkable list items"
        )
    decision = (section(sections, "owner decision required") or "").strip().lower()
    if not decision.startswith(("no", "нет")):
        return Readiness(
            False,
            "status:needs-owner",
            f"'Owner decision required' is not 'no' ({decision[:40]!r})",
        )
    if OWNER_APPROVED_LABEL not in issue.labels:
        stops = owner_stop_reasons(issue)
        if stops:
            return Readiness(
                False, "status:needs-owner", "owner stop condition(s): " + ", ".join(stops)
            )
    return Readiness(True)


# --------------------------------------------------------------------------- invariants


def find_violations(issues: list[Issue]) -> list[str]:
    out: list[str] = []
    in_progress = []
    for i in issues:
        st = i.status
        if i.is_open:
            if len(st) > 1:
                out.append(f"#{i.number} has {len(st)} status labels: {', '.join(st)}")
            if "status:done" in st:
                out.append(
                    f"#{i.number} is open but labelled status:done (close it or change status)"
                )
            if "status:in-progress" in st:
                in_progress.append(i.number)
        else:
            bad = [s for s in st if s in ("status:ready", "status:in-progress")]
            if bad:
                out.append(f"#{i.number} is closed but labelled {', '.join(bad)}")
    if len(in_progress) > 1:
        out.append(
            "more than one open status:in-progress issue: "
            + ", ".join(f"#{n}" for n in in_progress)
        )
    return out


# --------------------------------------------------------------------------- batch


def batch_can_start(state: dict) -> tuple[bool, str]:
    b = state["batch"]
    if b["status"] != "running":
        return (
            False,
            f"batch status is '{b['status']}' — owner must start a batch (`orch.py batch start`)",
        )
    if len(b["completed"]) >= b["limit"]:
        return (
            False,
            f"batch {b['id']} reached {len(b['completed'])}/{b['limit']} — STOP, OWNER REVIEW REQUIRED",
        )
    if len(b["attempts"]) >= b["max_attempts"]:
        return (
            False,
            f"batch {b['id']} used {len(b['attempts'])}/{b['max_attempts']} attempts — STOP, OWNER REVIEW REQUIRED",
        )
    return True, ""


def batch_start(state: dict, by: str, now: str, limit: int | None = None) -> None:
    b = state["batch"]
    if b["status"] == "running":
        raise SystemExit(f"batch {b['id']} is already running ({len(b['completed'])}/{b['limit']})")
    state["batch"] = {
        **b,
        "id": b["id"] + 1,
        "limit": limit or b["limit"],
        "status": "running",
        "approved_by": by,
        "started_at": now,
        "completed": [],
        "attempts": [],
        "idle_reason": None,
    }


def batch_stop(state: dict) -> None:
    state["batch"]["status"] = "stopped"


def batch_record(state: dict, issue: int, verdict: str) -> None:
    b = state["batch"]
    b["attempts"].append(issue)  # every finished worker run is one attempt
    if verdict == "done" and issue not in b["completed"]:
        b["completed"].append(issue)
    if len(b["completed"]) >= b["limit"] or len(b["attempts"]) >= b["max_attempts"]:
        b["status"] = "owner-review"


def batch_line(state: dict) -> str:
    b = state["batch"]
    n, lim = len(b["completed"]), b["limit"]
    if b["status"] == "owner-review":
        return f"AUTONOMOUS BATCH {b['id']}: {n}/{lim} — STOP — OWNER REVIEW REQUIRED"
    if b["status"] == "running":
        return f"AUTONOMOUS BATCH {b['id']}: {n}/{lim} (running; attempts {len(b['attempts'])}/{b['max_attempts']})"
    if b["status"] == "stopped":
        return f"AUTONOMOUS BATCH {b['id']}: {n}/{lim} — stopped by owner"
    if b.get("idle_reason") == "empty-queue":
        return (
            f"AUTONOMOUS BATCH {b['id']}: idle — queue empty, no worker dispatched ({n}/{lim}); "
            "owner: `/orch approve` on a complete issue"
        )
    return f"AUTONOMOUS BATCH: not running ({n}/{lim} last batch) — owner starts one explicitly"


# --------------------------------------------------------------------------- planner


def in_scope(issue: Issue, state: dict) -> bool:
    if DASHBOARD_LABEL in issue.labels:
        return False
    scope = state.get("scope_label")
    if scope:
        return scope in issue.labels
    return TEST_LABEL not in issue.labels


def sort_key(issue: Issue) -> tuple:
    return (
        PRIORITY_RANK.get(issue.priority or "", 3),
        0 if issue.type == "type:bug" else 1,
        issue.number,
    )


def ready_queue(issues: list[Issue], state: dict) -> list[Issue]:
    q = [i for i in issues if i.is_open and in_scope(i, state) and i.status == ["status:ready"]]
    return sorted(q, key=sort_key)


def active_issues(issues: list[Issue], state: dict) -> list[Issue]:
    return [
        i for i in issues if i.is_open and in_scope(i, state) and "status:in-progress" in i.labels
    ]


@dataclasses.dataclass
class PlanDecision:
    action: str  # select | active-exists | batch-stop | none-ready | invariant-violation
    selected: Issue | None = None
    rejected: list[tuple[Issue, Readiness]] = dataclasses.field(default_factory=list)
    message: str = ""


def plan(issues: list[Issue], state: dict) -> PlanDecision:
    """Pick exactly one next issue — or explain precisely why not. Pure: no I/O."""
    scoped = [i for i in issues if in_scope(i, state)]
    violations = find_violations(scoped)
    if violations:
        return PlanDecision("invariant-violation", message="; ".join(violations))
    active = active_issues(issues, state)
    if active:
        return PlanDecision(
            "active-exists",
            active[0],
            message=f"#{active[0].number} is already in progress — no second worker",
        )
    ok, why = batch_can_start(state)
    decision = PlanDecision("none-ready")
    # Whole queue is validated every run, so vague tasks are normalized before any worker
    # could meet them; the first passing one (in priority order) is the candidate.
    for issue in ready_queue(issues, state):
        r = check_ready(issue, state.get("trusted_authors") or [])
        if not r.ok:
            decision.rejected.append((issue, r))
        elif decision.selected is None:
            decision.selected = issue
    if decision.selected is None:
        decision.message = "no executable status:ready issue"
        return decision
    if not ok:
        return PlanDecision("batch-stop", decision.selected, decision.rejected, why)
    decision.action = "select"
    decision.message = f"selected #{decision.selected.number}"
    return decision


# --------------------------------------------------------------------------- execution brief


def worker_branch(issue: int) -> str:
    return f"orch/issue-{issue}"


_BODY_BRANCH_RE = re.compile(r"^\s*\**Branch:?\**:?\s*`([^`]+)`", re.MULTILINE | re.IGNORECASE)


def task_branch(issue: Issue, brief_text: str = "") -> str:
    """Where the work for an in-progress issue lives: the brief's BRANCH if the brief is for this
    issue, else a ``Branch: `name` `` line in the issue body (interactive tasks), else the
    worker default ``orch/issue-N``."""
    if brief_issue(brief_text) == issue.number and parse_brief(brief_text).get("BRANCH"):
        return parse_brief(brief_text)["BRANCH"]
    m = _BODY_BRANCH_RE.search(issue.body or "")
    return m.group(1) if m else worker_branch(issue.number)


def render_brief(issue: Issue, state: dict, base_sha: str, now: str) -> str:
    s = parse_sections(issue.body)
    b = state["batch"]
    out_of_scope = section(s, "out of scope") or ""
    lines = [
        "# Current task brief",
        "",
        "<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads",
        "     it; only the planner / finish step rewrites it. -->",
        "",
        f"ISSUE: #{issue.number}",
        f"TITLE: {issue.title}",
        f"URL: {issue.url}",
        f"PRIORITY: {(issue.priority or 'none').removeprefix('priority:')}",
        f"TYPE: {(issue.type or 'none').removeprefix('type:')}",
        f"BASE BRANCH: {state['canonical_branch']}",
        f"BASE SHA: {base_sha}",
        f"BRANCH: {worker_branch(issue.number)}",
        f"BATCH: {b['id']} (task {len(b['completed']) + 1}/{b['limit']})",
        f"SELECTED AT: {now}",
        "",
        "## Goal",
        "",
        section(s, "goal") or "",
        "",
        "## Acceptance criteria",
        "",
        section(s, "acceptance criteria") or "",
        "",
        "## Files / areas",
        "",
        section(s, "files")
        or "Not specified — locate via `.claude/skills/codebase-map` and real code.",
        "",
        "## Tests required",
        "",
        section(s, "tests") or "",
        "",
        (
            "Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → "
            "`npm run build && npm run test:unit` in `webapp-frontend/`."
        ),
        "",
        "## Do not touch",
        "",
        *[f"- {x}" for x in DEFAULT_DO_NOT_TOUCH],
        *([f"- issue 'Out of scope': {out_of_scope}"] if out_of_scope else []),
        "",
        "## Stop conditions",
        "",
        *[f"- {x}" for x in DEFAULT_STOP_CONDITIONS],
        "",
    ]
    return "\n".join(lines)


def render_idle_brief(last: str) -> str:
    return "\n".join(
        [
            "# Current task brief",
            "",
            "<!-- Written by the planner (scripts/orch.py). Exactly one active brief. -->",
            "",
            "ISSUE: none",
            f"LAST: {last}",
            "",
        ]
    )


def parse_brief(text: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r"^([A-Z][A-Z ]+):\s*(.*)$", text or "", re.MULTILINE):
        out.setdefault(m.group(1).strip(), m.group(2).strip())
    return out


def brief_issue(text: str) -> int | None:
    m = re.match(r"#(\d+)$", parse_brief(text).get("ISSUE", ""))
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------- worker guard / record


def worker_guard(issue: Issue, state: dict, brief_text: str, base: str) -> str | None:
    """Return None if a worker may run on `issue`, else the refusal reason."""
    if not ALLOWED_BASE_RE.match(base):
        return f"base '{base}' is not an allowed orchestration base"
    if base != state["canonical_branch"]:
        return f"base '{base}' != state canonical_branch '{state['canonical_branch']}'"
    if not issue.is_open:
        return f"#{issue.number} is closed"
    if issue.status != ["status:in-progress"]:
        return f"#{issue.number} status is {issue.status or 'none'}, expected exactly status:in-progress"
    if brief_issue(brief_text) != issue.number:
        return f"active brief is for {parse_brief(brief_text).get('ISSUE')}, not #{issue.number}"
    b = state["batch"]
    if b["status"] != "running":
        return f"batch status is '{b['status']}'"
    if issue.number in b["completed"]:
        return f"#{issue.number} already completed in batch {b['id']}"
    ok, why = batch_can_start(state)
    if not ok:
        return why
    return None


def forbidden_changes(changed_paths: list[str], diff_text: str) -> list[str]:
    out = [p for p in changed_paths if p.startswith(WORKER_FORBIDDEN_PREFIXES) or p == STATUS_PATH]
    if DESTRUCTIVE_MIGRATION_RE.search(diff_text or ""):
        out.append("destructive statement in an Alembic migration (drop/truncate/delete)")
    return out


RESULT_VERDICTS = ("done", "blocked", "needs-owner")
# Worker runs per issue per batch when the agent claimed done but only the deterministic gate
# (ruff/pytest/frontend/E2E) is red: the issue goes back to status:ready once, and the next
# worker resumes the same branch with the gate evidence. Then it is blocked for the owner.
GATE_RETRY_LIMIT = 2
RESULT_REQUIRED_FIELDS = ("VERDICT", "SUMMARY", "ACCEPTANCE", "TESTS")


def parse_result(text: str) -> dict[str, str]:
    """Worker result file: `VERDICT: done|blocked|needs-owner` + free-form sections."""
    fields = parse_brief(text)
    verdict = fields.get("VERDICT", "").lower()
    if verdict not in RESULT_VERDICTS:
        verdict = "blocked"
    return {
        "verdict": verdict,
        "text": (text or "").strip(),
        "error": result_contract_error(text) or "",
    }


def result_contract_error(text: str | None) -> str | None:
    """None if `text` satisfies the worker result contract, else why it does not.

    A missing/empty file and a malformed one are orchestration-contract failures — never a
    worker verdict — so they can neither mark a task done nor pass as an honest `blocked`.
    """
    if not (text or "").strip():
        return "result file missing or empty"
    fields = parse_brief(text)
    verdict = fields.get("VERDICT", "").lower()
    if verdict not in RESULT_VERDICTS:
        return (
            f"malformed result: VERDICT must be one of {', '.join(RESULT_VERDICTS)} "
            f"(got '{verdict or 'none'}')"
        )
    missing = [k for k in RESULT_REQUIRED_FIELDS if k not in fields]
    if missing:
        return "malformed result: missing " + ", ".join(missing)
    return None


def read_result(path: str | None) -> dict[str, str]:
    p = Path(path) if path else None
    return parse_result(p.read_text() if p and p.is_file() else "")


def final_verdict(
    agent_verdict: str,
    tests_ok: bool,
    commits_ahead: int,
    forbidden: list[str],
    merged: bool | None,
) -> tuple[str, str]:
    """Deterministic gate: the agent's claim alone never marks a task done."""
    if forbidden:
        return "needs-owner", "worker changed forbidden paths: " + "; ".join(forbidden)
    if agent_verdict != "done":
        return agent_verdict, f"worker reported {agent_verdict}"
    if commits_ahead <= 0:
        return "blocked", "worker reported done but produced no commits"
    if not tests_ok:
        return "blocked", "worker reported done but verification (ruff/pytest/frontend/e2e) failed"
    if merged is False:
        return "blocked", "merge into base failed (conflict) — branch left for review"
    return "done", "acceptance claimed by worker, verification green, merged into base"


# --------------------------------------------------------------------------- status page


@dataclasses.dataclass
class StatusContext:
    now: str
    state: dict
    issues: list[Issue]
    code_sha: str = "unknown"
    pr: dict | None = None
    brief_text: str = ""
    active_branch_sha: str | None = None
    active_branch: str | None = None
    last_worker_run: dict | None = None
    staging: str = "unknown"
    production: str = "unknown"


def _link(i: Issue) -> str:
    return f"[#{i.number}]({i.url})" if i.url else f"#{i.number}"


def render_status(ctx: StatusContext) -> str:
    st = ctx.state
    scoped = [i for i in ctx.issues if in_scope(i, st)]
    open_ = [i for i in scoped if i.is_open]
    active = active_issues(ctx.issues, st)
    queue = ready_queue(ctx.issues, st)
    blocked = sorted((i for i in open_ if "status:blocked" in i.labels), key=sort_key)
    needs_owner = sorted((i for i in open_ if "status:needs-owner" in i.labels), key=sort_key)
    backlog = sorted(
        (i for i in open_ if not i.status or i.status == ["status:backlog"]), key=sort_key
    )
    done = sorted(
        (i for i in scoped if not i.is_open and i.state_reason != "NOT_PLANNED" and i.closed_at),
        key=lambda i: i.closed_at or "",
        reverse=True,
    )[:5]
    violations = find_violations(scoped)
    pr = ctx.pr or {}
    brief = parse_brief(ctx.brief_text)

    L: list[str] = ["# Project Status", ""]
    L += [
        f"Updated: {ctx.now} · generated by `python scripts/orch.py status` — a VIEW; GitHub Issues + repo win.",
        "",
        "## Canonical",
        f"- Branch: `{st['canonical_branch']}`",
        f"- Code SHA: `{ctx.code_sha[:12]}` (last non-`{ORCH_COMMIT_PREFIX}` commit)",
    ]
    if st.get("canonical_pr"):
        checks = pr.get("checks", "unknown")
        draft = " draft" if pr.get("isDraft") else ""
        L.append(
            f"- PR: #{st['canonical_pr']} →main ({pr.get('state', '?').lower()}{draft}; CI {checks}) — never merged by automation"
        )
    L += ["", "## Current phase", f"{st.get('phase') or '—'}", ""]

    L.append("## IN PROGRESS")
    if active:
        for i in active:
            L.append(f"- {_link(i)} {i.title}")
            L.append(
                f"  - branch `{ctx.active_branch or task_branch(i, ctx.brief_text)}`: "
                + (
                    f"pushed `{ctx.active_branch_sha[:12]}`"
                    if ctx.active_branch_sha
                    else "not pushed yet"
                )
            )
            run = ctx.last_worker_run
            if run:
                L.append(
                    f"  - worker: {run.get('status')}/{run.get('conclusion') or '…'} · [run]({run.get('url')})"
                )
            else:
                L.append("  - worker: no Actions run recorded (local worker or not dispatched)")
    else:
        L.append("- none")
    if brief.get("ISSUE") and brief.get("ISSUE") != "none" and not active:
        L.append(f"- ⚠ brief points at {brief['ISSUE']} but no issue is status:in-progress")
    L.append("")

    L.append("## READY NEXT")
    if queue:
        for n, i in enumerate(queue[:3], 1):
            r = check_ready(i, st.get("trusted_authors") or [])
            flag = "" if r.ok else f" — ⚠ planner will reject: {r.reason}"
            L.append(
                f"{n}. {_link(i)} {i.title} ({(i.priority or 'no priority').removeprefix('priority:')}){flag}"
            )
    else:
        L.append("- none")
    L.append("")

    L.append("## BLOCKED")
    L += [f"- {_link(i)} {i.title}" for i in blocked] or ["- none"]
    L.append("")

    L.append("## NEEDS OWNER")
    L += [f"- {_link(i)} {i.title}" for i in needs_owner]
    L += [f"- {note}" for note in st.get("owner_notes") or []]
    if not needs_owner and not st.get("owner_notes"):
        L.append("- none")
    L.append("")

    if backlog:
        L.append("## BACKLOG (not ready)")
        L += [f"- {_link(i)} {i.title}" for i in backlog[:8]]
        if len(backlog) > 8:
            L.append(f"- … {len(backlog) - 8} more")
        L.append("")

    L.append("## RECENTLY DONE")
    L += [f"- {_link(i)} {i.title} ({(i.closed_at or '')[:10]})" for i in done] or ["- none"]
    L.append("")

    b = st["batch"]
    L += ["## AUTONOMOUS BATCH", f"- **{batch_line(st)}**"]
    if b["completed"]:
        L.append("- completed: " + ", ".join(f"#{n}" for n in b["completed"]))
    L.append(
        f"- stop condition: {b['limit']} completed tasks or {b['max_attempts']} attempts → OWNER REVIEW REQUIRED; no task starts after that"
    )
    L.append("")

    L += ["## ENVIRONMENTS", f"- Staging: {ctx.staging}", f"- Production: {ctx.production}", ""]

    if violations:
        L.append("## ⚠ STATE VIOLATIONS")
        L += [f"- {v}" for v in violations]
        L.append("")

    L += [
        "## Resume from any computer",
        "`git fetch && git switch develop/current && git pull` → read this file → open the IN PROGRESS issue →",
        "`python scripts/orch.py resume`. Details: docs/AGENT_EXECUTION_MODEL.md § Orchestration.",
        "",
    ]
    return "\n".join(L)


# --------------------------------------------------------------------------- I/O adapters


def run(cmd: list[str], check: bool = True, cwd: Path = ROOT) -> str:
    for attempt in range(3):  # gh/git over flaky networks: retry transient failures
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        transient = res.returncode != 0 and re.search(
            r"timeout|TLS|connection reset|502|503", res.stderr, re.IGNORECASE
        )
        if not transient or attempt == 2:
            break
    if check and res.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed ({res.returncode}): {res.stderr.strip()[:500]}")
    return res.stdout


class Gh:
    """Thin `gh` CLI adapter. Only issue numbers / fixed strings reach argv — issue text is
    passed via stdin/files, never interpolated into a shell."""

    FIELDS = "number,title,body,labels,state,stateReason,closedAt,author,url"

    def list_issues(self) -> list[Issue]:
        out: list[Issue] = []
        for st in ("open", "closed"):
            limit = "300" if st == "open" else "60"
            data = json.loads(
                run(["gh", "issue", "list", "--state", st, "--limit", limit, "--json", self.FIELDS])
            )
            out += [Issue.from_gh(d) for d in data]
        return out

    def get_issue(self, n: int) -> Issue:
        return Issue.from_gh(
            json.loads(run(["gh", "issue", "view", str(n), "--json", self.FIELDS]))
        )

    def set_status(self, n: int, status: str, current: set[str]) -> None:
        remove = [s for s in STATUS_LABELS if s in current and s != status]
        cmd = ["gh", "issue", "edit", str(n), "--add-label", status]
        if remove:
            cmd += ["--remove-label", ",".join(remove)]
        run(cmd)

    def comment(self, n: int, body: str) -> None:
        subprocess.run(
            ["gh", "issue", "comment", str(n), "--body-file", "-"],
            input=body,
            text=True,
            check=True,
            cwd=ROOT,
            capture_output=True,
        )

    def close(self, n: int) -> None:
        run(["gh", "issue", "close", str(n), "--reason", "completed"])

    def set_body(self, n: int, body: str) -> None:
        subprocess.run(
            ["gh", "issue", "edit", str(n), "--body-file", "-"],
            input=body,
            text=True,
            check=True,
            cwd=ROOT,
            capture_output=True,
        )

    def pr(self, n: int) -> dict:
        try:
            d = json.loads(
                run(["gh", "pr", "view", str(n), "--json", "state,isDraft,statusCheckRollup"])
            )
        except (RuntimeError, json.JSONDecodeError):
            return {}
        rollup = d.get("statusCheckRollup") or []
        concl = [(c.get("conclusion") or c.get("status") or "").upper() for c in rollup]
        if not concl:
            checks = "no checks"
        elif any(c in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT") for c in concl):
            checks = "RED"
        elif all(c in ("SUCCESS", "NEUTRAL", "SKIPPED") for c in concl):
            checks = "green"
        else:
            checks = "running"
        return {"state": d.get("state", "?"), "isDraft": d.get("isDraft"), "checks": checks}

    def last_run(self, workflow: str) -> dict | None:
        try:
            data = json.loads(
                run(
                    [
                        "gh",
                        "run",
                        "list",
                        "--workflow",
                        workflow,
                        "--limit",
                        "1",
                        "--json",
                        "status,conclusion,createdAt,url,displayTitle,headSha,headBranch",
                    ]
                )
            )
        except (RuntimeError, json.JSONDecodeError):
            return None
        return data[0] if data else None


def git_code_sha(branch: str) -> str:
    # On the canonical branch itself HEAD is authoritative (it may be about to be pushed).
    on_branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=False).strip() == branch
    ref = "HEAD" if on_branch else f"origin/{branch}"
    try:
        log = run(["git", "log", ref, "-n", "50", "--format=%H%x09%s"])
    except RuntimeError:
        log = run(["git", "log", "HEAD", "-n", "50", "--format=%H%x09%s"])
    for line in log.splitlines():
        sha, _, subject = line.partition("\t")
        if not subject.startswith(ORCH_COMMIT_PREFIX):
            return sha
    return log.split("\t", 1)[0] if log else "unknown"


def remote_branch_sha(branch: str) -> str | None:
    try:
        out = run(["git", "ls-remote", "--heads", "origin", branch])
    except RuntimeError:
        return None
    return out.split()[0] if out.strip() else None


def http_health(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            return f"/health {r.status}"
    except Exception as e:  # noqa: BLE001 — status page must never crash on a network hiccup
        return f"/health unreachable ({type(e).__name__})"


def read(path: str) -> str:
    p = ROOT / path
    return p.read_text(encoding="utf-8") if p.exists() else ""


def write(path: str, text: str) -> None:
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def load_state() -> dict:
    raw = read(STATE_PATH)
    state = default_state()
    if raw:
        loaded = json.loads(raw)
        state.update({k: v for k, v in loaded.items() if k != "batch"})
        state["batch"].update(loaded.get("batch", {}))
    return state


def save_state(state: dict) -> None:
    write(STATE_PATH, json.dumps(state, indent=2, ensure_ascii=False))


def utcnow() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


def gather_status(gh: Gh, state: dict, issues: list[Issue] | None = None) -> StatusContext:
    issues = issues if issues is not None else gh.list_issues()
    run(["git", "fetch", "--quiet", "origin", state["canonical_branch"]], check=False)
    ctx = StatusContext(now=utcnow(), state=state, issues=issues, brief_text=read(BRIEF_PATH))
    ctx.code_sha = git_code_sha(state["canonical_branch"])
    if state.get("canonical_pr"):
        ctx.pr = gh.pr(state["canonical_pr"])
    active = active_issues(issues, state)
    if active:
        ctx.active_branch = task_branch(active[0], ctx.brief_text)
        ctx.active_branch_sha = remote_branch_sha(ctx.active_branch)
        run_ = gh.last_run("orch-worker.yml")
        if run_ and f"#{active[0].number}" in (run_.get("displayTitle") or ""):
            ctx.last_worker_run = run_
    stg = gh.last_run("deploy-staging.yml")
    health = http_health(
        state.get("staging_health_url") or "https://staging.app.bimoool.com/health"
    )
    ctx.staging = (
        f"last deploy {stg['createdAt'][:16].replace('T', ' ')} UTC {stg.get('conclusion') or stg.get('status')} · {health}"
        if stg
        else health
    )
    prod = gh.last_run("deploy.yml")
    ctx.production = (
        f"last deploy {prod['createdAt'][:16].replace('T', ' ')} UTC ({prod.get('conclusion')}, main `{(prod.get('headSha') or '')[:7]}`) — "
        "orchestrator NEVER deploys production"
        if prod
        else "never deployed by automation"
    )
    return ctx


def commit_and_push(paths: list[str], message: str, branch: str) -> bool:
    """Commit orchestration files to the canonical branch and push (retry on races).
    Refuses to run unless the checkout IS that branch — never writes elsewhere."""
    if not ALLOWED_BASE_RE.match(branch):
        raise SystemExit(f"refusing to push to '{branch}'")
    current = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if current != branch:
        raise SystemExit(f"checkout is on '{current}', not '{branch}' — refusing to commit state")
    run(["git", "add", "--", *paths])
    if not run(["git", "diff", "--cached", "--name-only"]).strip():
        return False
    run(["git", "commit", "-m", f"{ORCH_COMMIT_PREFIX} {message}"])
    for _ in range(4):
        if (
            subprocess.run(
                ["git", "push", "origin", f"HEAD:{branch}"],
                cwd=ROOT,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        ):
            return True
        run(["git", "pull", "--no-rebase", "--no-edit", "origin", branch])
    raise SystemExit("push failed after retries")


# --------------------------------------------------------------------------- commands


def refresh_status(
    gh: Gh, state: dict, issues: list[Issue] | None = None, publish: bool = False
) -> str:
    text = render_status(gather_status(gh, state, issues))
    write(STATUS_PATH, text)
    if publish and state.get("dashboard_issue"):
        header = (
            "> Auto-generated mirror of `docs/PROJECT_STATUS.md` on "
            f"`{state['canonical_branch']}` — do not edit; it is overwritten.\n\n"
        )
        gh.set_body(state["dashboard_issue"], header + text)
    return text


def cmd_where(args, gh: Gh) -> int:
    state = load_state()
    print(render_status(gather_status(gh, state)))
    return 0


def cmd_status(args, gh: Gh) -> int:
    state = load_state()
    refresh_status(gh, state, publish=args.publish)
    print(f"wrote {STATUS_PATH}")
    if args.push:
        commit_and_push([STATUS_PATH], "refresh PROJECT_STATUS", state["canonical_branch"])
    return 0


def cmd_check(args, gh: Gh) -> int:
    state = load_state()
    issues = gh.list_issues()
    v = find_violations([i for i in issues if in_scope(i, state)])
    for line in v:
        print("VIOLATION:", line)
    if brief_issue(read(BRIEF_PATH)) and not active_issues(issues, state):
        print("VIOLATION: brief is active but no issue is status:in-progress")
        v.append("brief")
    print("OK" if not v else f"{len(v)} violation(s)")
    return 1 if v else 0


def cmd_batch(args, gh: Gh) -> int:
    state = load_state()
    if args.op == "show":
        print(batch_line(state))
        print(json.dumps(state["batch"], indent=2))
        return 0
    if args.op == "start":
        batch_start(
            state,
            by=args.by or os.environ.get("GITHUB_ACTOR") or "owner",
            now=utcnow(),
            limit=args.limit,
        )
    elif args.op == "stop":
        batch_stop(state)
    save_state(state)
    refresh_status(gh, state, publish=args.publish)
    print(batch_line(state))
    if args.push:
        commit_and_push(
            [STATE_PATH, STATUS_PATH],
            f"batch {args.op} → {batch_line(state)}",
            state["canonical_branch"],
        )
    return 0


def apply_rejections(gh: Gh, decision: PlanDecision) -> None:
    for issue, r in decision.rejected:
        gh.set_status(issue.number, r.label or "status:needs-owner", issue.labels)
        gh.comment(
            issue.number,
            f"🧭 **Planner:** not executable autonomously → `{r.label}`.\n\nReason: {r.reason}\n\n"
            "Fix the issue (see `.github/ISSUE_TEMPLATE/implementation.md`) and set `status:ready` again.",
        )
        issue.labels = (issue.labels - set(STATUS_LABELS)) | {r.label or "status:needs-owner"}


def cmd_plan(args, gh: Gh) -> int:
    state = load_state()
    issues = gh.list_issues()
    decision = plan(issues, state)
    args.decision = decision
    print(
        f"PLANNER ({'APPLY' if args.apply else 'DRY RUN'}): {decision.action} — {decision.message}"
    )
    for issue, r in decision.rejected:
        print(f"  reject #{issue.number} → {r.label}: {r.reason}")
    if decision.selected:
        print(f"  candidate: #{decision.selected.number} {decision.selected.title}")
    out = os.environ.get("GITHUB_OUTPUT")
    selected = decision.selected.number if decision.action == "select" and decision.selected else ""
    if not args.apply:
        return 0
    apply_rejections(gh, decision)
    if decision.action == "select" and decision.selected:
        issue = decision.selected
        base_sha = run(["git", "rev-parse", "HEAD"]).strip()
        gh.set_status(issue.number, "status:in-progress", issue.labels)
        issue.labels = (issue.labels - set(STATUS_LABELS)) | {"status:in-progress"}
        write(BRIEF_PATH, render_brief(issue, state, base_sha, utcnow()))
        b = state["batch"]
        gh.comment(
            issue.number,
            f"🧭 **Planner:** selected as batch {b['id']} task {len(b['completed']) + 1}/{b['limit']} → `status:in-progress`.\n\n"
            f"- base: `{state['canonical_branch']}` @ `{base_sha[:12]}`\n- worker branch: `{worker_branch(issue.number)}`\n"
            f"- brief: `{BRIEF_PATH}` on `{state['canonical_branch']}`",
        )
    elif decision.action == "batch-stop" and state["batch"]["status"] == "running":
        state["batch"]["status"] = "owner-review"
    elif decision.action == "none-ready" and state["batch"]["status"] == "running":
        # Empty queue: stop presenting the batch as coding; `/orch approve` restarts it.
        state["batch"]["status"] = "idle"
        state["batch"]["idle_reason"] = "empty-queue"
    args.decision = decision
    save_state(state)
    refresh_status(gh, state, issues, publish=args.publish)
    if args.push:
        commit_and_push(
            [STATE_PATH, BRIEF_PATH, STATUS_PATH],
            f"planner {decision.action} {('#' + str(selected)) if selected else ''}".strip(),
            state["canonical_branch"],
        )
    if out:
        with open(out, "a") as f:
            f.write(f"issue={selected}\naction={decision.action}\n")
    return 0


def cmd_resume(args, gh: Gh) -> int:
    state = load_state()
    issues = gh.list_issues()
    active = active_issues(issues, state)
    print(batch_line(state))
    if not active:
        print(
            "No active task. Next: `python scripts/orch.py plan` (dry run) — see READY NEXT in docs/PROJECT_STATUS.md."
        )
        return 0
    i = active[0]
    br = task_branch(i, read(BRIEF_PATH))
    sha = remote_branch_sha(br)
    print(f"ACTIVE: #{i.number} {i.title}\n  {i.url}\n  brief: {BRIEF_PATH}")
    if sha:
        print(f"  pushed branch {br} @ {sha[:12]} — CONTINUE IT, do not start a duplicate:")
        print(f"    git fetch origin {br} && git worktree add ../pullup-issue-{i.number} {br}")
    else:
        print(
            f"  no pushed branch yet — start it: git worktree add -b {br} ../pullup-issue-{i.number} origin/{state['canonical_branch']}"
        )
    print("  then read the issue's latest checkpoint comment and docs/WORKER_AGENT.md")
    return 0


def cmd_checkpoint(args, gh: Gh) -> int:
    state = load_state()
    sha = args.sha or run(["git", "rev-parse", "HEAD"]).strip()
    branch = args.branch or run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    remote = remote_branch_sha(branch)
    pushed = (
        "✅ pushed"
        if remote == sha
        else f"⚠ NOT pushed (remote {remote[:12] if remote else 'missing'})"
    )
    gh.comment(args.issue, f"📍 **Checkpoint** `{branch}` @ `{sha[:12]}` — {pushed}\n\n{args.note}")
    if args.status:
        refresh_status(gh, state, publish=args.publish)
    print(f"checkpoint posted to #{args.issue} ({pushed})")
    return 0 if remote == sha else 2


def cmd_worker_guard(args, gh: Gh) -> int:
    state = load_state()
    issue = gh.get_issue(args.issue)
    reason = worker_guard(issue, state, read(BRIEF_PATH), args.base)
    if reason:
        print(f"WORKER REFUSED: {reason}")
        return 1
    print(f"WORKER ALLOWED: #{issue.number} on {worker_branch(issue.number)}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"branch={worker_branch(issue.number)}\n")
    return 0


def cmd_worker_record(args, gh: Gh) -> int:
    """Finish step: labels, issue report, batch counter, idle brief, status, (optional) push."""
    state = load_state()
    issue = gh.get_issue(args.issue)
    result = read_result(args.result_file) if args.result_file else {"error": "", "text": ""}
    forbidden = [x for x in (args.forbidden or "").split("\n") if x.strip()]
    agent_verdict = parse_result(result["text"])["verdict"] if args.result_file else args.verdict
    gate_red_only = (
        not result["error"]
        and agent_verdict == "done"
        and args.commits_ahead > 0
        and not forbidden
        and args.tests_ok != "1"
    )
    if result["error"]:
        # Orchestration-contract failure: the agent's claim is unusable, so nothing is done.
        verdict = "needs-owner" if forbidden else "blocked"
        why = (
            f"ORCH CONTRACT FAILURE — {result['error']} (commits: {args.commits_ahead}, "
            f"verification {'green' if args.tests_ok == '1' else 'not green'}); "
            "branch left pushed, work preserved, NOT marked done"
        )
    else:
        verdict, why = final_verdict(
            agent_verdict,
            args.tests_ok == "1",
            args.commits_ahead,
            forbidden,
            # With a result file (Actions) an unknown merge state means "not merged": never done.
            None if args.merged == "" and not args.result_file else args.merged == "1",
        )
    label = {
        "done": "status:done",
        "blocked": "status:blocked",
        "needs-owner": "status:needs-owner",
    }[verdict]
    batch_record(state, issue.number, verdict)
    runs = state["batch"]["attempts"].count(issue.number)
    if (
        verdict == "blocked"
        and gate_red_only
        and runs < GATE_RETRY_LIMIT
        and batch_can_start(state)[0]
    ):
        label = "status:ready"
        why += (
            f" — AUTO-RETRY ({runs}/{GATE_RETRY_LIMIT} runs): back to status:ready; the next "
            "worker resumes this branch with the gate evidence below"
        )
    gh.set_status(issue.number, label, issue.labels)
    evidence = ""
    if getattr(args, "evidence_file", None) and Path(args.evidence_file).is_file():
        evidence = Path(args.evidence_file).read_text().strip()[-6000:]
    report = [
        f"🤖 **Worker result: {verdict.upper()}** — {why}",
        "",
        f"- branch: `{worker_branch(issue.number)}` @ `{(args.sha or '')[:12]}`",
        f"- verification: {args.tests_summary or ('green' if args.tests_ok == '1' else 'FAILED')}",
        f"- run: {args.run_url or 'local'}",
        f"- {batch_line(state)}",
        "",
        *(
            ["<details><summary>Gate evidence</summary>", "", evidence, "", "</details>", ""]
            if evidence
            else []
        ),
        "<details><summary>Worker report</summary>",
        "",
        result["text"] or "(no usable result file — see ORCH CONTRACT FAILURE above)",
        "",
        "</details>",
    ]
    gh.comment(issue.number, "\n".join(report))
    if verdict == "done":
        gh.close(issue.number)
    write(BRIEF_PATH, render_idle_brief(f"#{issue.number} → {verdict} ({utcnow()})"))
    save_state(state)
    refresh_status(gh, state, publish=args.publish)
    if args.push:
        commit_and_push(
            [STATE_PATH, BRIEF_PATH, STATUS_PATH],
            f"worker #{issue.number} → {verdict}; {batch_line(state)}",
            state["canonical_branch"],
        )
    ok, why_not = batch_can_start(state)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"verdict={verdict}\ncontinue={'true' if ok else 'false'}\n")
    print(
        f"#{issue.number} → {verdict}: {why}\n{batch_line(state)}"
        + ("" if ok else f"\nnext planner run will not start a task: {why_not}")
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="orch.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("where")
    s = sub.add_parser("status")
    s.add_argument("--publish", action="store_true", help="also overwrite the dashboard issue body")
    s.add_argument("--push", action="store_true")
    sub.add_parser("check")
    s = sub.add_parser("batch")
    s.add_argument("op", choices=["show", "start", "stop"])
    s.add_argument("--limit", type=int)
    s.add_argument("--by")
    s.add_argument("--publish", action="store_true")
    s.add_argument("--push", action="store_true")
    s = sub.add_parser("plan")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--publish", action="store_true")
    s.add_argument("--push", action="store_true")
    sub.add_parser("resume")
    s = sub.add_parser("checkpoint")
    s.add_argument("--issue", type=int, required=True)
    s.add_argument("--note", required=True)
    s.add_argument("--sha")
    s.add_argument("--branch")
    s.add_argument("--status", action="store_true", help="also refresh PROJECT_STATUS.md locally")
    s.add_argument("--publish", action="store_true")
    s = sub.add_parser("worker-guard")
    s.add_argument("--issue", type=int, required=True)
    s.add_argument("--base", required=True)
    s = sub.add_parser("worker-record")
    s.add_argument("--issue", type=int, required=True)
    s.add_argument("--verdict", choices=["done", "blocked", "needs-owner"], default="blocked")
    s.add_argument("--result-file")
    s.add_argument("--tests-ok", choices=["0", "1"], default="0")
    s.add_argument("--tests-summary", default="")
    s.add_argument("--commits-ahead", type=int, default=0)
    s.add_argument("--forbidden", default="")
    s.add_argument("--merged", choices=["", "0", "1"], default="")
    s.add_argument("--sha", default="")
    s.add_argument("--run-url", default="")
    s.add_argument("--evidence-file", default="", help="gate failure tails for the report")
    s.add_argument("--publish", action="store_true")
    s.add_argument("--push", action="store_true")
    args = p.parse_args(argv)
    handler = {
        "where": cmd_where,
        "status": cmd_status,
        "check": cmd_check,
        "batch": cmd_batch,
        "plan": cmd_plan,
        "resume": cmd_resume,
        "checkpoint": cmd_checkpoint,
        "worker-guard": cmd_worker_guard,
        "worker-record": cmd_worker_record,
    }[args.cmd]
    return handler(args, Gh())


if __name__ == "__main__":
    sys.exit(main())
