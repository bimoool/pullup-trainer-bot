"""Offline tests for one incident's owner-bound, at-most-once R3 recovery admission."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guarded_comment_dispatch as d

from tools.tests.test_guarded_comment_dispatch import API

SHA = "e9f32dd194aab140f63c445e0c2d2eddf59b2b91"
MANIFEST = "/root/backups/prod-pre-e9f32dd-20261115T075403Z.manifest"
CONFIRM = "ROLLBACK-R3-prod-e9f32dd-20261115T075403Z-247039"
COMMAND = f"/pullup incident-r3-apply {SHA} {CONFIRM}"
TRUSTED = "34176de72e42ebdb9e964dff1407af65ebfb4204"


class IncidentAPI(API):
    def __init__(self):
        super().__init__()
        self.pr["number"] = 399
        self.pr["head"]["sha"] = SHA
        self.pr.update(state="closed", merged=True)
        self.event["issue"]["number"] = 399
        self.event["comment"]["body"] = COMMAND
        self.event["comment"]["issue_url"] = f"https://api.github.com/repos/{d.REPO}/issues/399"
        self.event["comment"].update(
            created_at="2026-11-15T09:00:00Z", updated_at="2026-11-15T09:00:00Z"
        )
        self.runtime["run_attempt"] = "1"
        self.runs = {}
        self.jobs = {}
        for run_id, job_id, workflow, conclusion in (
            (43691971076, 132744343548, "production-deploy.yml", "failure"),
            (43692580932, 132746139599, "production-rollback.yml", "success"),
        ):
            self.runs[run_id] = {
                "id": run_id,
                "path": f".github/workflows/{workflow}",
                "head_branch": "main",
                "head_sha": TRUSTED,
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": conclusion,
                "run_attempt": 1,
            }
            self.jobs[run_id] = {
                "total_count": 1,
                "jobs": [
                    {
                        "id": job_id,
                        "run_id": run_id,
                        "status": "completed",
                        "conclusion": conclusion,
                    }
                ],
            }

    def __call__(self, method, path, body=None):
        if method == "GET" and path.startswith("actions/runs/"):
            self.calls.append((method, path, body))
            run_id = int(path.split("/")[2])
            return copy.deepcopy(self.jobs[run_id] if "/jobs?" in path else self.runs[run_id])
        if method == "POST" and path == "issues/399/comments":
            return super().__call__(method, "issues/400/comments", body)
        return super().__call__(method, path, body)


class DispatchTests(unittest.TestCase):
    def test_only_fixed_incident_command_routes_to_existing_main_workflow(self):
        a = IncidentAPI()
        self.assertIn("accepted", a.run())
        self.assertEqual(
            a.dispatched()[0][1], "actions/workflows/production-rollback.yml/dispatches"
        )
        payload = a.dispatched()[0][2]
        self.assertEqual(payload["ref"], "main")
        self.assertEqual(
            payload["inputs"],
            {
                "kind": "R3",
                "manifest": MANIFEST,
                "mode": "apply",
                "confirm": CONFIRM,
                "incident_request_comment_id": "10",
                "incident_dispatcher_run_id": "500",
            },
        )
        self.assertIn("duplicate", a.run())
        self.assertEqual(len(a.dispatched()), 1)

    def test_near_miss_commands_are_refused(self):
        for body in (
            COMMAND + "; id",
            COMMAND.replace(SHA, "a" * 40),
            COMMAND.replace("R3-", "R1-"),
            COMMAND + " extra",
            COMMAND.replace("247039", "247040"),
        ):
            with self.subTest(body=body), self.assertRaises(d.Refused):
                d.command(body)

    def test_owner_pr_and_latest_evidence_fail_closed(self):
        for case in (
            "owner",
            "pr",
            "run_path",
            "run_head",
            "rerun",
            "job",
            "check_failed",
            "edited",
            "comment_pr",
            "dispatcher_rerun",
        ):
            a = IncidentAPI()
            if case == "owner":
                a.event["sender"]["id"] = 99
            if case == "pr":
                a.event["issue"]["number"] = 400
            if case == "run_path":
                a.runs[43691971076]["path"] = ".github/workflows/evil.yml"
            if case == "run_head":
                a.runs[43692580932]["head_sha"] = "b" * 40
            if case == "rerun":
                a.runs[43692580932]["run_attempt"] = 2
            if case == "job":
                a.jobs[43692580932]["jobs"][0]["id"] += 1
            if case == "check_failed":
                a.runs[43692580932]["conclusion"] = "failure"
            if case == "edited":
                a.event["comment"]["updated_at"] = "2026-11-15T09:01:00Z"
            if case == "comment_pr":
                a.event["comment"]["issue_url"] += "0"
            if case == "dispatcher_rerun":
                a.runtime["run_attempt"] = "2"
            with self.subTest(case=case), self.assertRaises(d.Refused):
                a.run()
            self.assertFalse(a.dispatched())

    def test_uncertain_dispatch_claim_blocks_new_owner_comment(self):
        a = IncidentAPI()
        a.fail = "actions/workflows/production-rollback.yml/dispatches"
        with self.assertRaises(TimeoutError):
            a.run()
        a.fail = None
        a.event["comment"]["id"] = 11
        # The persisted incident claim is independent of the request comment ID.
        original = a.__class__.__call__

        def api(method, path, body=None):
            if path == "issues/comments/11":
                return copy.deepcopy(a.event["comment"])
            return original(a, method, path, body)

        self.assertIn("duplicate", d.dispatch(a.event, a.runtime, api))
        self.assertEqual(len(a.dispatched()), 1)


class WorkflowTests(unittest.TestCase):
    def test_child_admission_precedes_ssh_and_uses_trusted_checkout(self):
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/production-rollback.yml"
        ).read_text()
        self.assertIn("python3 tools/incident_r3_recovery_client.py", workflow)
        self.assertLess(
            workflow.index("python3 tools/incident_r3_recovery_client.py"), workflow.index("ssh -i")
        )
        self.assertIn("ref: ${{ github.workflow_sha }}", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)


class ExecutionTests(unittest.TestCase):
    def fixture(self):
        import incident_r3_recovery_client as client

        a = IncidentAPI()
        a.run()
        head = "f" * 40
        for run_id, workflow, event, actor in (
            (500, d.DISPATCHER, "issue_comment", {"id": 1, "login": "bimoool"}),
            (
                600,
                ".github/workflows/production-rollback.yml",
                "workflow_dispatch",
                {"id": d.BOT_ID, "login": "github-actions[bot]"},
            ),
        ):
            a.runs[run_id] = {
                "id": run_id,
                "path": workflow,
                "event": event,
                "head_branch": "main",
                "head_sha": head,
                "run_attempt": 1,
                "status": "in_progress",
                "conclusion": None,
                "actor": actor,
                "triggering_actor": actor,
            }
        env = {
            "GITHUB_REPOSITORY": d.REPO,
            "GITHUB_WORKFLOW_REF": f"{d.REPO}/.github/workflows/production-rollback.yml@refs/heads/main",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": head,
            "GITHUB_RUN_ID": "600",
            "GITHUB_RUN_ATTEMPT": "1",
            "KIND": "R3",
            "MANIFEST": MANIFEST,
            "MODE": "apply",
            "CONFIRM": CONFIRM,
            "INCIDENT_REQUEST_COMMENT_ID": "10",
            "INCIDENT_DISPATCHER_RUN_ID": "500",
        }
        return client, a, env

    def test_execution_claim_is_persisted_once_and_blocks_another_run(self):
        client, a, env = self.fixture()
        client.authorize_execution(a, env)
        self.assertIn("execution reserved", a.comments[-1]["body"])
        a.runs[601] = dict(a.runs[600], id=601)
        env["GITHUB_RUN_ID"] = "601"
        with self.assertRaisesRegex(d.Refused, "already claimed"):
            client.authorize_execution(a, env)
        self.assertEqual(sum("execution reserved" in c["body"] for c in a.comments), 1)

    def test_every_execution_binding_refuses_before_claim(self):
        for case in (
            "manual_actor",
            "manual_trigger",
            "dispatcher_actor",
            "run_attempt",
            "branch",
            "sha",
            "comment_edited",
            "comment_owner",
            "comment_pr",
            "comment_id",
            "claim_missing",
            "claim_wrong_request",
            "check_retried",
            "kind",
            "manifest",
            "token",
        ):
            client, a, env = self.fixture()
            if case == "manual_actor":
                a.runs[600]["actor"] = {"id": 1, "login": "bimoool"}
            if case == "manual_trigger":
                a.runs[600]["triggering_actor"] = {"id": 1, "login": "bimoool"}
            if case == "dispatcher_actor":
                a.runs[500]["actor"] = {"id": d.BOT_ID, "login": "github-actions[bot]"}
            if case == "run_attempt":
                env["GITHUB_RUN_ATTEMPT"] = "2"
            if case == "branch":
                env["GITHUB_REF"] = "refs/heads/evil"
            if case == "sha":
                a.runs[600]["head_sha"] = "b" * 40
            if case == "comment_edited":
                a.event["comment"]["updated_at"] += "changed"
            if case == "comment_owner":
                a.event["comment"]["user"]["login"] = "impostor"
            if case == "comment_pr":
                a.event["comment"]["issue_url"] += "0"
            if case == "comment_id":
                a.event["comment"]["id"] = 11
            if case == "claim_missing":
                a.comments = []
            if case == "claim_wrong_request":
                a.comments[0]["body"] = a.comments[0]["body"].replace(":10:500", ":11:500")
            if case == "check_retried":
                a.jobs[43692580932]["jobs"][0]["id"] += 1
            if case == "kind":
                env["KIND"] = "R1"
            if case == "manifest":
                env["MANIFEST"] += ".other"
            if case == "token":
                env["CONFIRM"] += "other"
            before = copy.deepcopy(a.comments)
            with self.subTest(case=case), self.assertRaises(d.Refused):
                client.authorize_execution(a, env)
            self.assertEqual(a.comments, before)

    def test_uncertain_execution_claim_never_replays(self):
        client, a, env = self.fixture()

        def uncertain(method, path, body=None):
            result = a(method, path, body)
            if method == "POST":
                raise TimeoutError
            return result

        with self.assertRaises(TimeoutError):
            client.authorize_execution(uncertain, env)
        with self.assertRaisesRegex(d.Refused, "already claimed"):
            client.authorize_execution(a, env)
