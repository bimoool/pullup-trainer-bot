"""Synthetic GitHub check/run/job metadata for offline gate tests."""

from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

REPO = "bimoool/pullup-trainer-bot"
SHA = "a" * 40
PATHS = {
    "ruff": "tests.yml",
    "pytest": "tests.yml",
    "frontend build": "tests.yml",
    "e2e": "e2e.yml",
    "codex-review": "claude-code-review.yml",
    "security": "security-review.yml",
    "rehearse": "rehearsal-harness.yml",
}


class CheckAPI:
    def __init__(self, *, defaults=True):
        self.checks, self.runs, self.jobs, self.workflows, self.calls = [], {}, {}, {}, []
        if defaults:
            for index, (name, path) in enumerate(PATHS.items(), 1):
                self.add(name, run_id=100 + index, job_id=1000 + index, workflow=path)

    def add(
        self,
        name,
        *,
        run_id,
        job_id,
        workflow=None,
        app=15368,
        status="completed",
        conclusion="success",
        started="2026-11-10T12:00:00Z",
        attempt=1,
    ):
        path = ".github/workflows/" + (workflow or PATHS[name])
        workflow_id = next(
            (i for i, w in self.workflows.items() if w["path"] == path), len(self.workflows) + 10
        )
        self.workflows[workflow_id] = {"id": workflow_id, "path": path, "state": "active"}
        details = f"https://github.com/{REPO}/actions/runs/{run_id}/job/{job_id}"
        check = {
            "id": job_id,
            "name": name,
            "status": status,
            "conclusion": conclusion,
            "head_sha": SHA,
            "started_at": started,
            "completed_at": started,
            "details_url": details,
            "check_suite": {"id": run_id + 10000},
            "app": {"id": app, "slug": "github-actions" if app == 15368 else "other"},
        }
        self.checks.append(check)
        self.runs[run_id] = {
            "id": run_id,
            "head_sha": SHA,
            "workflow_id": workflow_id,
            "path": path,
            "check_suite_id": run_id + 10000,
            "run_attempt": attempt,
            "repository": {"full_name": REPO},
        }
        self.jobs.setdefault(run_id, []).append(
            {
                "id": job_id,
                "run_id": run_id,
                "run_attempt": attempt,
                "head_sha": SHA,
                "name": name,
                "status": status,
                "conclusion": conclusion,
                "started_at": started,
                "completed_at": started,
                "html_url": details,
                "check_run_url": f"https://api.github.com/repos/{REPO}/check-runs/{job_id}",
            }
        )
        return check

    def __call__(self, method, path, body=None):
        self.calls.append((method, path))
        split = urlsplit(path)
        page = int(parse_qs(split.query).get("page", ["1"])[0])
        if "/check-runs?" in path:
            return {
                "total_count": len(self.checks),
                "check_runs": deepcopy(self.checks[(page - 1) * 100 : page * 100]),
            }
        bits = split.path.split("/")
        if bits[:2] == ["actions", "runs"]:
            run_id = int(bits[2])
            if len(bits) == 3:
                return deepcopy(self.runs[run_id])
            if bits[3] == "jobs":
                jobs = self.jobs[run_id]
                return {
                    "total_count": len(jobs),
                    "jobs": deepcopy(jobs[(page - 1) * 100 : page * 100]),
                }
        if bits[:2] == ["actions", "workflows"]:
            return deepcopy(self.workflows[int(bits[2])])
        raise AssertionError(path)
