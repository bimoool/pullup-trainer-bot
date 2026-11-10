"""Release gates must distinguish superseded attempts from current failing checks."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guarded_comment_dispatch as dispatch

from tools.tests.check_fixtures import SHA, CheckAPI


class CurrentCheckTests(unittest.TestCase):
    def test_superseded_cancelled_draft_review_does_not_block_new_success(self):
        api = CheckAPI()
        current = next(c for c in api.checks if c["name"] == "codex-review")
        current["started_at"] = "2026-11-10T12:29:31Z"
        api.jobs[105][0]["started_at"] = current["started_at"]
        current["completed_at"] = current["started_at"]
        api.jobs[105][0]["completed_at"] = current["started_at"]
        api.add(
            "codex-review",
            run_id=42815992838,
            job_id=129829110546,
            conclusion="cancelled",
            started="2026-11-10T12:28:08Z",
        )
        dispatch.green_checks(api, SHA)

    def test_new_failure_pending_or_cancelled_never_uses_old_success(self):
        for status, result in (
            ("completed", "failure"),
            ("in_progress", None),
            ("queued", None),
            ("completed", "cancelled"),
        ):
            with self.subTest(status=status, result=result):
                api = CheckAPI()
                api.add(
                    "codex-review",
                    run_id=200,
                    job_id=2000,
                    status=status,
                    conclusion=result,
                    started="2026-11-10T12:02:00Z",
                )
                with self.assertRaises(dispatch.Refused):
                    dispatch.green_checks(api, SHA)

    def test_rerun_of_older_run_is_ordered_by_actual_execution(self):
        api = CheckAPI()
        api.add("codex-review", run_id=200, job_id=2000, started="2026-11-10T12:02:00Z")
        api.add(
            "codex-review",
            run_id=105,
            job_id=2001,
            attempt=2,
            conclusion="failure",
            started="2026-11-10T12:03:00Z",
        )
        with self.assertRaises(dispatch.Refused):
            dispatch.green_checks(api, SHA)
        # A later successful execution of that same older run is also current.
        api.checks[-1]["conclusion"] = "success"
        api.jobs[105][-1]["conclusion"] = "success"
        dispatch.green_checks(api, SHA)

    def test_different_app_or_workflow_cannot_mask_failure(self):
        for app, workflow in ((99, "claude-code-review.yml"), (15368, "other.yml")):
            with self.subTest(app=app, workflow=workflow):
                api = CheckAPI()
                api.checks[4]["conclusion"] = "failure"
                api.jobs[105][0]["conclusion"] = "failure"
                api.add(
                    "codex-review",
                    run_id=200,
                    job_id=2000,
                    app=app,
                    workflow=workflow,
                    started="2026-11-10T12:02:00Z",
                )
                with self.assertRaises(dispatch.Refused):
                    dispatch.green_checks(api, SHA)

    def test_foreign_failure_is_not_hidden_by_required_success(self):
        for app, workflow in ((99, "claude-code-review.yml"), (15368, "other.yml")):
            with self.subTest(app=app, workflow=workflow):
                api = CheckAPI()
                api.add(
                    "codex-review",
                    run_id=200,
                    job_id=2000,
                    app=app,
                    workflow=workflow,
                    conclusion="failure",
                    started="2026-11-10T12:02:00Z",
                )
                with self.assertRaises(dispatch.Refused):
                    dispatch.green_checks(api, SHA)

    def test_required_context_must_come_from_its_expected_workflow(self):
        api = CheckAPI()
        api.checks.pop(4)
        api.add("codex-review", run_id=200, job_id=2000, workflow="other.yml")
        with self.assertRaises(dispatch.Refused):
            dispatch.green_checks(api, SHA)

    def test_missing_wrong_or_untrusted_provenance_refuses(self):
        changes = [
            lambda a: a.checks[0].pop("app"),
            lambda a: a.checks[0].update(app=None),
            lambda a: a.checks[0].update(check_suite=None),
            lambda a: a.runs[101].update(repository=None),
            lambda a: a.checks[0].update(head_sha="b" * 40),
            lambda a: a.checks[0].update(details_url="https://other.example/token"),
            lambda a: a.runs[101].update(head_sha="b" * 40),
            lambda a: a.runs[101]["repository"].update(full_name="other/repo"),
            lambda a: a.runs[101].update(path=".github/workflows/other.yml"),
            lambda a: a.checks[0].update(check_suite={"id": 99}),
            lambda a: a.jobs[101][0].update(check_run_url="https://other.example/1"),
            lambda a: a.jobs[101][0].update(started_at=None),
            lambda a: a.jobs[101][0].update(run_attempt=None),
            lambda a: a.workflows[10].update(path=".github/workflows/tests.yml@evil"),
        ]
        for change in changes:
            with self.subTest(change=change):
                api = CheckAPI()
                change(api)
                with self.assertRaises(dispatch.Refused):
                    dispatch.green_checks(api, SHA)

    def test_new_job_missing_from_check_snapshot_refuses(self):
        api = CheckAPI()
        api.add("codex-review", run_id=105, job_id=2000, attempt=2, started="2026-11-10T12:02:00Z")
        api.checks.pop()  # job metadata already sees the rerun; check listing is stale
        with self.assertRaises(dispatch.Refused):
            dispatch.green_checks(api, SHA)

    def test_two_jobs_with_same_context_in_one_attempt_are_ambiguous(self):
        api = CheckAPI()
        api.add("codex-review", run_id=105, job_id=2000, started="2026-11-10T12:02:00Z")
        with self.assertRaises(dispatch.Refused):
            dispatch.green_checks(api, SHA)

    def test_multiple_workflows_classify_contexts_remain_separate(self):
        api = CheckAPI()
        api.add("changes / classify", run_id=201, job_id=2001, workflow="tests.yml")
        api.add(
            "changes / classify", run_id=202, job_id=2002, workflow="e2e.yml", conclusion="failure"
        )
        with self.assertRaises(dispatch.Refused):
            dispatch.green_checks(api, SHA)

    def test_full_pagination_and_cached_run_lookup(self):
        api = CheckAPI(defaults=False)
        for index in range(105):
            api.add(f"extra-{index}", run_id=100, job_id=1000 + index, workflow="tests.yml")
        from current_checks import ensure_green

        ensure_green(api, SHA, set())
        self.assertIn(
            ("GET", f"commits/{SHA}/check-runs?filter=latest&per_page=100&page=2"), api.calls
        )
        self.assertIn(("GET", "actions/runs/100/jobs?filter=all&per_page=100&page=2"), api.calls)
        self.assertEqual(api.calls.count(("GET", "actions/runs/100")), 1)

    def test_missing_or_incomplete_pagination_refuses(self):
        from current_checks import CheckRefused, ensure_green

        base = CheckAPI()
        for field in ("check_runs", "jobs"):
            with self.subTest(field=field):

                def api(method, path, field=field):
                    result = base(method, path)
                    if field in result:
                        result["total_count"] += 1
                    return result

                with self.assertRaises(CheckRefused):
                    ensure_green(api, SHA, set())
