"""Synthetic GitHub provenance and strict anonymous-output validation."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server_control_client as c

from tools.tests.test_guarded_comment_dispatch import API, SHA


class ControlAPI(API):
    def __call__(self, method, path, body=None):
        if method == "GET" and path == "":
            return {
                "id": 123,
                "full_name": c.REPO,
                "default_branch": "main",
                "owner": {"id": 1, "login": "bimoool"},
            }
        if method == "GET" and path == "actions/runs/500":
            return {
                "path": ".github/workflows/cloud-command-dispatch.yml",
                "event": "issue_comment",
                "head_branch": "main",
            }
        return super().__call__(method, path, body)


class ClientTests(unittest.TestCase):
    def fixture(self):
        a = ControlAPI()
        a.event["comment"]["body"] = f"/pullup server-readiness {SHA}"
        a.event["comment"]["issue_url"] = f"https://api.github.com/repos/{c.REPO}/issues/400"
        a.run()
        e = {
            "GITHUB_REPOSITORY": c.REPO,
            "GITHUB_WORKFLOW_REF": f"{c.REPO}/{c.WORKFLOW}@refs/heads/main",
            "OPERATION": "readiness",
            "CANDIDATE_SHA": SHA,
            "OPERATION_ID": "ops-10",
            "PR_NUMBER": "400",
            "REQUEST_COMMENT_ID": "10",
        }
        return a, e

    def test_child_rechecks_owner_pr_sha_and_trusted_claim(self):
        a, e = self.fixture()
        self.assertEqual(c.authorize(a, e), (400, "readiness", SHA, "ops-10"))
        for key, value in [
            ("OPERATION_ID", "ops-11"),
            ("CANDIDATE_SHA", "b" * 40),
            ("GITHUB_WORKFLOW_REF", f"{c.REPO}/{c.WORKFLOW}@refs/heads/evil"),
        ]:
            with self.subTest(key=key):
                bad = dict(e)
                bad[key] = value
                with self.assertRaises(c.Refused):
                    c.authorize(a, bad)

    def test_missing_claim_and_cross_pr_comment_refused(self):
        a, e = self.fixture()
        a.comments = []
        with self.assertRaises(c.Refused):
            c.authorize(a, e)
        a, e = self.fixture()
        a.event["comment"]["issue_url"] = f"https://api.github.com/repos/{c.REPO}/issues/999"
        with self.assertRaises(c.Refused):
            c.authorize(a, e)

    def test_secrets_extra_fields_or_wrong_operation_never_exported(self):
        r = {
            "operation_id": "ops-10",
            "candidate": SHA,
            "action": "prepare",
            "stage": "object-present",
            "state": "VERIFIED",
            "facts": {"candidate_present": True},
        }
        self.assertEqual(c.safe_receipt(__import__("json").dumps(r).encode(), SHA, "ops-10"), r)
        for bad in [
            dict(r, token="sensitive"),
            dict(r, operation_id="ops-11"),
            dict(r, facts={"error": "https://secret.invalid/?token=123"}),
            dict(r, state="UNKNOWN"),
        ]:
            with self.assertRaises(c.Refused):
                c.safe_receipt(__import__("json").dumps(bad).encode(), SHA, "ops-10")

    def test_restore_success_without_confirmed_cleanup_is_refused(self):
        receipt = {
            "operation_id": "ops-10",
            "candidate": SHA,
            "action": "restore",
            "stage": "verified",
            "state": "VERIFIED",
            "facts": {},
        }
        with self.assertRaises(c.Refused):
            c.safe_receipt(__import__("json").dumps(receipt).encode(), SHA, "ops-10")
        receipt["facts"]["cleanup_verified"] = True
        self.assertEqual(
            c.safe_receipt(__import__("json").dumps(receipt).encode(), SHA, "ops-10"), receipt
        )


class AdoptionClientTests(unittest.TestCase):
    def fixture(self):

        from tools.tests.check_fixtures import CheckAPI
        from tools.tests.test_rollback_r1_recovery import HEAD, RecoveryAPI

        a = RecoveryAPI()
        checks = CheckAPI()
        a.event["comment"]["body"] = f"/pullup server-adopt-runner {SHA}"
        a.runs[500] = {
            "id": 500,
            "path": ".github/workflows/cloud-command-dispatch.yml",
            "event": "issue_comment",
            "head_branch": "main",
            "head_sha": HEAD,
            "run_attempt": 1,
            "status": "in_progress",
            "actor": {"id": 1, "login": "bimoool"},
            "triggering_actor": {"id": 1, "login": "bimoool"},
        }
        a.runs[600] = {
            "id": 600,
            "path": c.WORKFLOW,
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": HEAD,
            "run_attempt": 1,
            "status": "in_progress",
            "actor": {"id": c.BOT_ID, "login": "github-actions[bot]"},
            "triggering_actor": {"id": c.BOT_ID, "login": "github-actions[bot]"},
        }

        def api(method, path, body=None):
            if path.startswith("git/commits/"):
                return {"tree": {"sha": "tree"}}
            if path == "commits/main":
                return {"commit": {"tree": {"sha": "tree"}}}
            if "check-runs?" in path or (
                path.startswith("actions/")
                and (
                    any(f"/{run_id}" in path for run_id in checks.runs)
                    or "/workflows/" in path
                    and path.split("/")[2].isdigit()
                )
            ):
                return checks(method, path, body)
            return a(method, path, body)

        import guarded_comment_dispatch as dispatcher

        dispatcher.dispatch(a.event, a.runtime, api)
        env = {
            "GITHUB_REPOSITORY": c.REPO,
            "GITHUB_WORKFLOW_REF": f"{c.REPO}/{c.WORKFLOW}@refs/heads/main",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_RUN_ID": "600",
            "GITHUB_SHA": HEAD,
            "OPERATION": "adopt-runner",
            "CANDIDATE_SHA": SHA,
            "OPERATION_ID": "ops-10",
            "PR_NUMBER": "400",
            "REQUEST_COMMENT_ID": "10",
        }
        return a, checks, api, env

    def test_adoption_child_rechecks_full_ci_and_exact_owner_provenance(self):
        _a, checks, api, env = self.fixture()
        self.assertEqual(c.authorize(api, env), (400, "adopt-runner", SHA, "ops-10"))
        checks.checks[0]["conclusion"] = "failure"
        with self.assertRaises(c.Refused):
            c.authorize(api, env)

    def test_edited_owner_rerun_and_manual_child_refused(self):
        for case in ["edited", "rerun", "actor", "triggering_actor"]:
            a, _, api, env = self.fixture()
            if case == "edited":
                a.event["comment"]["updated_at"] += "edited"
            elif case == "rerun":
                env["GITHUB_RUN_ATTEMPT"] = "2"
            else:
                a.runs[600][case]["id"] = 1
            with self.subTest(case=case), self.assertRaises(c.Refused):
                c.authorize(api, env)
