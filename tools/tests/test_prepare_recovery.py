"""Same-operation prepare recovery keeps original admission and child attribution."""

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guarded_comment_dispatch as d
import server_control_client as c

from tools.tests.test_guarded_comment_dispatch import SHA
from tools.tests.test_server_control_client import ControlAPI


class RecoveryAPI(ControlAPI):
    def __init__(self):
        super().__init__()
        self.original = copy.deepcopy(self.event["comment"])
        self.original.update(
            body=f"/pullup server-prepare {SHA}",
            issue_url=f"https://api.github.com/repos/{d.REPO}/issues/400",
        )
        self.event["comment"] = copy.deepcopy(self.original)
        self.event["comment"].update(id=11, body=f"/pullup server-prepare-recover {SHA} 10")

    def __call__(self, method, path, body=None):
        if method == "GET" and path == "issues/comments/10":
            return copy.deepcopy(self.original)
        if method == "GET" and path == "issues/comments/11":
            return copy.deepcopy(self.event["comment"])
        return super().__call__(method, path, body)


class RecoveryTests(unittest.TestCase):
    def run_recovery(self, api):
        with patch.object(d, "green_checks"), patch.object(c, "green_checks"):
            return api.run()

    def test_same_id_dispatch_child_and_late_original_dedup(self):
        a = RecoveryAPI()
        self.assertIn("accepted", self.run_recovery(a))
        inputs = a.dispatched()[0][2]["inputs"]
        self.assertEqual(
            inputs,
            {
                "operation": "prepare",
                "candidate_sha": SHA,
                "operation_id": "ops-10",
                "pr_number": "400",
                "request_comment_id": "10",
            },
        )
        env = {
            "GITHUB_REPOSITORY": c.REPO,
            "GITHUB_WORKFLOW_REF": f"{c.REPO}/{c.WORKFLOW}@refs/heads/main",
            "OPERATION": "prepare",
            "CANDIDATE_SHA": SHA,
            "OPERATION_ID": "ops-10",
            "PR_NUMBER": "400",
            "REQUEST_COMMENT_ID": "10",
        }
        with patch.object(c, "green_checks"):
            self.assertEqual(c.authorize(a, env), (400, "prepare", SHA, "ops-10"))
        self.assertIn("duplicate", self.run_recovery(a))
        a.event["comment"] = a.original
        self.assertIn("duplicate", self.run_recovery(a))
        self.assertEqual(len(a.dispatched()), 1)

    def test_original_text_owner_pr_and_current_head_are_required(self):
        for mutation in ("body", "owner", "pr", "head", "sender"):
            a = RecoveryAPI()
            if mutation == "body":
                a.original["body"] += " "
            elif mutation == "owner":
                a.original["user"]["id"] = 99
            elif mutation == "pr":
                a.original["issue_url"] += "1"
            elif mutation == "head":
                a.pr["head"]["sha"] = "b" * 40
            else:
                a.event["sender"]["id"] = 99
            with self.subTest(mutation=mutation), self.assertRaises(d.Refused):
                self.run_recovery(a)
            self.assertFalse(a.dispatched())

    def test_claim_before_uncertain_dispatch_prevents_retry(self):
        a = RecoveryAPI()
        a.fail = "actions/workflows/server-control.yml/dispatches"
        with self.assertRaises(TimeoutError):
            self.run_recovery(a)
        a.fail = None
        self.assertIn("duplicate", self.run_recovery(a))
        self.assertEqual(len(a.dispatched()), 1)

    def test_preexisting_original_claim_refuses_recovery(self):
        a = RecoveryAPI()
        recovery = a.event["comment"]
        a.event["comment"] = a.original
        self.run_recovery(a)
        a.event["comment"] = recovery
        with self.assertRaisesRegex(d.Refused, "already claimed"):
            self.run_recovery(a)
        self.assertEqual(len(a.dispatched()), 1)

    def test_recovery_child_rechecks_provenance(self):
        for mutation in ("owner", "text", "pr", "dispatcher", "malformed"):
            a = RecoveryAPI()
            self.run_recovery(a)
            if mutation == "owner":
                a.event["comment"]["user"]["id"] = 99
            elif mutation == "text":
                a.event["comment"]["body"] += " "
            elif mutation == "pr":
                a.event["comment"]["issue_url"] += "1"
            elif mutation == "dispatcher":
                a.comments[0]["body"] = a.comments[0]["body"].replace(":11:500 -->", ":11:501 -->")
            else:
                a.comments[0]["body"] = a.comments[0]["body"].replace(":11:500 -->", ":11:bad -->")
            env = {
                "GITHUB_REPOSITORY": c.REPO,
                "GITHUB_WORKFLOW_REF": f"{c.REPO}/{c.WORKFLOW}@refs/heads/main",
                "OPERATION": "prepare",
                "CANDIDATE_SHA": SHA,
                "OPERATION_ID": "ops-10",
                "PR_NUMBER": "400",
                "REQUEST_COMMENT_ID": "10",
            }
            with (
                self.subTest(mutation=mutation),
                patch.object(c, "green_checks"),
                self.assertRaises(c.Refused),
            ):
                c.authorize(a, env)

    def test_same_id_concurrent_children_have_one_prepare_effect(self):
        import tempfile
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path

        from tools.tests.test_server_control import t as server

        entered, release = threading.Event(), threading.Event()
        effects = []

        def prepare(sha):
            effects.append(sha)
            entered.set()
            self.assertTrue(release.wait(5))
            return {"candidate_present": True}

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "LEDGER", Path(directory)),
            patch.object(server, "trusted_directory"),
            patch.object(server, "regular"),
            patch.object(server.os, "geteuid", return_value=0),
            patch.object(
                server,
                "acquire_existing",
                side_effect=lambda _: __import__("os").open("/dev/null", 0),
            ),
            patch.object(server, "no_other_operations"),
            patch.object(server, "object_present", return_value=False),
            patch.object(server, "prepare", side_effect=prepare),
            ThreadPoolExecutor(2) as pool,
        ):
            original = pool.submit(server.execute, "prepare", SHA, "ops-10")
            self.assertTrue(entered.wait(5))
            recovery = pool.submit(server.execute, "prepare", SHA, "ops-10")
            self.assertEqual(recovery.result(timeout=5)["state"], "RUNNING")
            release.set()
            self.assertEqual(original.result(timeout=5)["state"], "VERIFIED")
            self.assertEqual(server.execute("prepare", SHA, "ops-10")["state"], "VERIFIED")
            self.assertEqual(effects, [SHA])
            with self.assertRaises(server.Refused):
                server.execute("prepare", "b" * 40, "ops-10")
