"""Offline run/job provenance, owner binding and no-replay recovery regressions."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guarded_comment_dispatch as d
import rollback_r1_recovery as r1
import rollback_r1_recovery_client as client

from tools.tests.test_cloud_control_continuity import MANIFEST, SHA, TOKEN
from tools.tests.test_guarded_comment_dispatch import API

BODY = f"/pullup rollback-r1-apply {SHA} {MANIFEST} {TOKEN} 1234 1235"
HEAD = "b" * 40


class RecoveryAPI(API):
    def __init__(self):
        super().__init__()
        self.event["comment"].update(
            body=BODY,
            issue_url=f"https://api.github.com/repos/{d.REPO}/issues/400",
            created_at="2026-11-15T12:02:00Z",
            updated_at="2026-11-15T12:02:00Z",
        )
        self.runtime["run_attempt"] = "1"
        bot = {"id": d.BOT_ID, "login": "github-actions[bot]"}
        self.runs, self.jobs = {}, {}
        for run_id, path, title, conclusion, start, end in [
            (
                1234,
                r1.PRODUCTION,
                f"Guarded production {SHA} apply {'c' * 12} {'c' * 12}",
                "failure",
                "11:59:00",
                "12:00:30",
            ),
            (
                1235,
                r1.WORKFLOW,
                f"Guarded rollback R1 check {MANIFEST}",
                "success",
                "12:01:00",
                "12:01:30",
            ),
        ]:
            self.runs[run_id] = {
                "id": run_id,
                "path": path,
                "event": "workflow_dispatch",
                "head_branch": "main",
                "head_sha": HEAD,
                "run_attempt": 1,
                "status": "completed",
                "conclusion": conclusion,
                "actor": bot.copy(),
                "triggering_actor": bot.copy(),
                "display_title": title,
                "updated_at": f"2026-11-15T{end}Z",
            }
            self.jobs[run_id] = {
                "total_count": 1,
                "jobs": [
                    {
                        "id": run_id + 10000,
                        "run_id": run_id,
                        "name": "deploy" if run_id == 1234 else "rollback",
                        "status": "completed",
                        "conclusion": conclusion,
                        "started_at": f"2026-11-15T{start}Z",
                        "completed_at": f"2026-11-15T{end}Z",
                    }
                ],
            }

    def __call__(self, method, path, body=None):
        if method == "GET":
            if path == "":
                return {
                    "id": 123,
                    "full_name": d.REPO,
                    "default_branch": "main",
                    "owner": {"id": 1, "login": "bimoool"},
                }
            if path.startswith("actions/runs/"):
                run = int(path.split("/")[2])
                return copy.deepcopy(self.jobs[run] if "/jobs?" in path else self.runs[run])
            if path.startswith("compare/"):
                return {"merge_base_commit": {"sha": HEAD}}
            if path.startswith("actions/workflows/") and "/runs?" in path:
                workflow = path.split("/")[2]
                return {
                    "workflow_runs": [
                        copy.deepcopy(run)
                        for run in self.runs.values()
                        if run["path"].endswith("/" + workflow)
                    ]
                }
            if path.startswith("issues/comments?"):
                return copy.deepcopy(self.comments)
        result = super().__call__(method, path, body)
        if method == "POST" and path == "issues/400/comments":
            result["issue_url"] = f"https://api.github.com/repos/{d.REPO}/issues/400"
        return result


class RecoveryTests(unittest.TestCase):
    def fixture(self):
        api = RecoveryAPI()
        api.run()
        for run_id, path, event, actor in [
            (500, d.DISPATCHER, "issue_comment", {"id": 1, "login": "bimoool"}),
            (
                600,
                r1.WORKFLOW,
                "workflow_dispatch",
                {"id": d.BOT_ID, "login": "github-actions[bot]"},
            ),
        ]:
            api.runs[run_id] = {
                "id": run_id,
                "path": path,
                "event": event,
                "head_branch": "main",
                "head_sha": HEAD,
                "run_attempt": 1,
                "status": "in_progress",
                "actor": actor.copy(),
                "triggering_actor": actor.copy(),
                "display_title": f"Guarded rollback R1 apply {MANIFEST}",
            }
        inputs = r1.parse(BODY, d.require)[1]
        env = {key.upper(): value for key, value in inputs.items()}
        env.update(
            GITHUB_REPOSITORY=d.REPO,
            GITHUB_WORKFLOW_REF=f"{d.REPO}/{r1.WORKFLOW}@refs/heads/main",
            GITHUB_REF="refs/heads/main",
            GITHUB_RUN_ATTEMPT="1",
            GITHUB_SHA=HEAD,
            GITHUB_RUN_ID="600",
            RECOVERY_PR_NUMBER="400",
            RECOVERY_REQUEST_COMMENT_ID="10",
            RECOVERY_DISPATCHER_RUN_ID="500",
        )
        return api, env

    def test_recovery_routes_without_product_ci_and_execution_is_claimed_once(self):
        api, env = self.fixture()
        self.assertEqual(api.dispatched()[0][2]["ref"], "main")
        client.authorize_execution(api, env)
        with self.assertRaisesRegex(d.Refused, "already claimed"):
            client.authorize_execution(api, env)
        self.assertEqual(
            sum(
                r1.marker(r1.parse(BODY, d.require)[1], True) in row["body"] for row in api.comments
            ),
            1,
        )

    def test_every_provenance_failure_refuses_before_execution_claim(self):
        for case in [
            "owner",
            "edited",
            "pr_head",
            "manual",
            "trigger",
            "rerun",
            "claim",
            "kind",
            "token",
            "check_kind",
            "job",
            "check_order",
            "ancestry",
        ]:
            api, env = self.fixture()
            if case == "owner":
                api.event["comment"]["user"]["id"] = 9
            if case == "edited":
                api.event["comment"]["updated_at"] += "edited"
            if case == "pr_head":
                api.pr["head"]["sha"] = "e" * 40
            if case == "manual":
                api.runs[600]["actor"]["id"] = 1
            if case == "trigger":
                api.runs[600]["triggering_actor"]["id"] = 1
            if case == "rerun":
                api.runs[1234]["run_attempt"] = 2
            if case == "claim":
                api.comments = []
            if case == "kind":
                env["KIND"] = "R3"
            if case == "token":
                env["CONFIRM"] += "0"
            if case == "check_kind":
                api.runs[1235]["display_title"] = f"Guarded rollback R3 check {MANIFEST}"
            if case == "job":
                api.jobs[1235]["jobs"][0]["run_id"] = 99
            if case == "check_order":
                api.jobs[1235]["jobs"][0]["started_at"] = "2026-11-15T11:00:00Z"
            if case == "ancestry":
                api.runs[1235]["head_sha"] = "c" * 40
            before = copy.deepcopy(api.comments)
            with self.subTest(case=case), self.assertRaises(d.Refused):
                client.authorize_execution(api, env)
            self.assertEqual(api.comments, before)

    def test_newer_live_operation_or_wrong_manifest_time_invalidates_old_evidence(self):
        for case in ["new_deploy", "new_check", "manifest_time"]:
            api = RecoveryAPI()
            if case == "manifest_time":
                api.jobs[1234]["jobs"][0]["completed_at"] = "2026-11-15T11:59:59Z"
            else:
                source = 1234 if case == "new_deploy" else 1235
                api.runs[1240] = dict(api.runs[source], id=1240, updated_at="2026-11-15T12:03:00Z")
            with self.subTest(case=case), self.assertRaises(d.Refused):
                api.run()
            self.assertFalse(api.dispatched())

    def test_incident_claim_on_another_pr_blocks_new_dispatch(self):
        api = RecoveryAPI()
        api.comments = [
            {
                "body": r1.marker(r1.parse(BODY, d.require)[1]),
                "user": {"id": d.BOT_ID, "login": "github-actions[bot]"},
                "issue_url": f"https://api.github.com/repos/{d.REPO}/issues/401",
            }
        ]
        self.assertIn("duplicate", api.run())
        self.assertFalse(api.dispatched())

    def test_uncertain_post_is_durable_and_no_replay(self):
        api, env = self.fixture()

        def uncertain(method, path, body=None):
            result = api(method, path, body)
            if method == "POST":
                raise TimeoutError
            return result

        with self.assertRaises(TimeoutError):
            client.authorize_execution(uncertain, env)
        with self.assertRaisesRegex(d.Refused, "already claimed"):
            client.authorize_execution(api, env)
