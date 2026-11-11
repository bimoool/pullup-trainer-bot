"""Select current, attributed CI attempts without hiding other failing contexts."""

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime

REPO = "bimoool/pullup-trainer-bot"
ACTIONS_APP_ID = 15368
REQUIRED_WORKFLOWS = {
    "ruff": "tests.yml",
    "pytest": "tests.yml",
    "frontend build": "tests.yml",
    "e2e": "e2e.yml",
    "codex-review": "claude-code-review.yml",
    "security": "security-review.yml",
    "rehearse": "rehearsal-harness.yml",
}


class CheckRefused(Exception):
    """Fixed diagnostic text only; never include API bodies or credentials."""


def require(condition, message):
    if not condition:
        raise CheckRefused(message)


def positive(value):
    return type(value) is int and value > 0


def timestamp(value):
    require(isinstance(value, str) and bool(value), "missing check execution time")
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise CheckRefused("invalid check execution time") from None
    require(result.tzinfo is not None, "execution time has no timezone")
    return result


def pages(api, path, field):
    rows, expected, seen = [], None, set()
    for page in range(1, 11):
        response = api("GET", f"{path}&per_page=100&page={page}")
        require(isinstance(response, dict), "invalid evidence response")
        total, batch = response.get("total_count"), response.get(field)
        require(type(total) is int and 0 <= total <= 1000, "invalid or excessive evidence count")
        require(isinstance(batch, list) and len(batch) <= 100, "invalid evidence page")
        require(expected is None or expected == total, "evidence changed during pagination")
        expected = total
        for row in batch:
            require(isinstance(row, dict), "invalid evidence row")
            identity = row.get("id")
            require(positive(identity) and identity not in seen, "duplicate or missing evidence ID")
            seen.add(identity)
            rows.append(row)
        require(len(rows) <= expected, "inconsistent evidence count")
        if len(rows) == expected:
            return rows
        require(len(batch) == 100, "incomplete evidence pagination")
    raise CheckRefused("evidence pagination limit")


def current_checks(api, sha):
    require(re.fullmatch("[0-9a-f]{40}", sha) is not None, "invalid candidate SHA")
    checks = pages(api, f"commits/{sha}/check-runs?filter=latest", "check_runs")
    runs, workflows, jobs, groups, foreign = {}, {}, {}, {}, []
    job_route = re.compile(
        rf"https://github\.com/{re.escape(REPO)}/actions/runs/([0-9]+)/job/([0-9]+)"
    )
    check_route = re.compile(
        rf"https://api\.github\.com/repos/{re.escape(REPO)}/check-runs/([0-9]+)"
    )

    for check in checks:
        name, app = check.get("name"), check.get("app", {})
        require(isinstance(app, dict), "missing check app")
        require(
            isinstance(name, str) and bool(name) and positive(app.get("id")),
            "missing check context",
        )
        require(check.get("head_sha") == sha, "check SHA mismatch")
        if app["id"] != ACTIONS_APP_ID:
            # Do not collapse checks for another app whose execution provenance is unknown.
            foreign.append((check, None))
            continue
        require(app.get("slug") == "github-actions", "wrong Actions app")
        require(isinstance(check.get("details_url"), str), "missing check job URL")
        match = job_route.fullmatch(check["details_url"])
        require(match is not None, "untrusted check job URL")
        run_id, job_id = map(int, match.groups())
        if run_id not in runs:
            run = api("GET", f"actions/runs/{run_id}")
            require(isinstance(run, dict), "invalid workflow run")
            require(isinstance(run.get("repository"), dict), "missing workflow repository")
            require(
                run.get("id") == run_id and run.get("head_sha") == sha, "workflow run SHA mismatch"
            )
            require(
                run.get("repository", {}).get("full_name") == REPO, "workflow repository mismatch"
            )
            workflow_id = run.get("workflow_id")
            require(
                positive(workflow_id) and positive(run.get("run_attempt")),
                "missing workflow attempt",
            )
            if workflow_id not in workflows:
                workflows[workflow_id] = api("GET", f"actions/workflows/{workflow_id}")
            workflow = workflows[workflow_id]
            require(isinstance(workflow, dict), "invalid workflow metadata")
            path = workflow.get("path", "")
            require(isinstance(path, str), "missing workflow path")
            require(
                workflow.get("id") == workflow_id and workflow.get("state") == "active",
                "unknown workflow provenance",
            )
            # Exact API paths only. Unknown ref-qualified/reusable forms fail closed.
            require(
                re.fullmatch(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml", path) is not None,
                "invalid workflow path",
            )
            require(run.get("path") == path, "workflow path mismatch")
            runs[run_id] = run
            jobs[run_id] = pages(api, f"actions/runs/{run_id}/jobs?filter=all", "jobs")
        run = runs[run_id]
        require(isinstance(check.get("check_suite"), dict), "missing check suite")
        require(
            check.get("check_suite", {}).get("id") == run.get("check_suite_id")
            and positive(run.get("check_suite_id")),
            "check suite mismatch",
        )
        found = [job for job in jobs[run_id] if job["id"] == job_id]
        require(len(found) == 1, "check job missing")
        job = found[0]
        require(isinstance(job.get("check_run_url"), str), "missing job check URL")
        check_id = check_route.fullmatch(job["check_run_url"])
        require(
            check_id is not None and int(check_id[1]) == check["id"], "check/job binding mismatch"
        )
        require(
            job.get("run_id") == run_id and job.get("head_sha") == sha and job.get("name") == name,
            "job context mismatch",
        )
        require(
            positive(job.get("run_attempt")) and job["run_attempt"] <= run["run_attempt"],
            "invalid job attempt",
        )
        require(job.get("html_url") == check["details_url"], "job URL mismatch")
        require(
            (job.get("status"), job.get("conclusion"))
            == (check.get("status"), check.get("conclusion")),
            "check/job status changed",
        )
        started = timestamp(job.get("started_at"))
        require(timestamp(check.get("started_at")) == started, "check/job execution time mismatch")
        if check.get("status") == "completed":
            completed = timestamp(job.get("completed_at"))
            # GitHub can record skipped jobs as completed before started: no
            # execution took place. Still bind both timestamps exactly; only
            # executed jobs must have a nonnegative execution interval.
            require(
                timestamp(check.get("completed_at")) == completed
                and (check.get("conclusion") == "skipped" or completed >= started),
                "check/job completion time mismatch",
            )
        key = (app["id"], run["workflow_id"], name)
        groups.setdefault(key, []).append((started, run_id, job["run_attempt"], check, run["path"]))

    selected = list(foreign)
    for key, records in groups.items():
        attempts = {(r[1], r[2]) for r in records}
        require(len(attempts) == len(records), "ambiguous duplicate jobs in one context/attempt")
        times = {r[0] for r in records}
        require(len(times) == len(records), "ambiguous execution ordering")
        current = max(records, key=lambda r: r[0])
        known_checks = {r[3]["id"] for r in records}
        # A rerun of an older run can execute later than a newly created run. Inspect
        # actual job attempts, not run_number/run ID or the run's original created_at.
        for run_id in {r[1] for r in records}:
            named = [job for job in jobs[run_id] if job.get("name") == key[2]]
            require(
                len({job.get("run_attempt") for job in named}) == len(named),
                "ambiguous jobs in workflow attempt",
            )
            for job in named:
                if job.get("name") != key[2]:
                    continue
                started = timestamp(job.get("started_at"))
                if started >= current[0]:
                    require(isinstance(job.get("check_run_url"), str), "missing job check URL")
                    linked = check_route.fullmatch(job["check_run_url"])
                    require(
                        linked is not None and int(linked[1]) in known_checks,
                        "new job attempt has no check evidence",
                    )
        selected.append((current[3], current[4]))
    return selected


def ensure_green(api, sha, required):
    require(set(required) <= REQUIRED_WORKFLOWS.keys(), "unknown required context")
    selected = current_checks(api, sha)
    satisfied = {
        c["name"]
        for c, path in selected
        if c["name"] in REQUIRED_WORKFLOWS
        and path == ".github/workflows/" + REQUIRED_WORKFLOWS[c["name"]]
        and c.get("status") == "completed"
        and c.get("conclusion") == "success"
    }
    require(set(required) <= satisfied, "required current checks not green or wrongly attributed")
    require(
        all(
            c.get("status") == "completed"
            and c.get("conclusion") in {"success", "skipped", "neutral"}
            for c, _ in selected
        ),
        "current non-green check exists",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sha")
    parser.add_argument(
        "--required", nargs="+", choices=REQUIRED_WORKFLOWS, default=list(REQUIRED_WORKFLOWS)
    )
    args = parser.parse_args()

    def api(method, path):
        request = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/{path}",
            method=method,
            headers={
                "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    try:
        ensure_green(api, args.sha, args.required)
    except CheckRefused as exc:
        parser.exit(1, f"CI refused: {exc}\n")
    except urllib.error.HTTPError as exc:
        parser.exit(1, f"CI evidence unavailable: HTTP {exc.code}\n")
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError, AttributeError):
        parser.exit(1, "CI evidence unavailable or invalid\n")
    print("Current attributed CI checks are green.")


if __name__ == "__main__":
    main()
