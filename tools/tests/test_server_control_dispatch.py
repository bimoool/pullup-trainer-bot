"""Control extension must retain all existing owner/PR/default-branch guards."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guarded_comment_dispatch as t

from tools.tests.test_guarded_comment_dispatch import API, SHA


class DispatchTests(unittest.TestCase):
    def test_readiness_exact_and_at_most_once(self):
        api = API()
        api.event["comment"]["body"] = f"/pullup server-readiness {SHA}"
        self.assertIn("accepted", api.run())
        call = api.dispatched()[0]
        self.assertEqual(call[1], "actions/workflows/server-control.yml/dispatches")
        self.assertEqual(
            call[2],
            {
                "ref": "main",
                "inputs": {
                    "operation": "readiness",
                    "candidate_sha": SHA,
                    "operation_id": "ops-10",
                    "pr_number": "400",
                    "request_comment_id": "10",
                },
            },
        )
        self.assertIn("duplicate", api.run())
        self.assertEqual(len(api.dispatched()), 1)

    def test_changed_sha_sender_and_runtime_rejected(self):
        for change in ["sender", "sha", "workflow"]:
            api = API()
            api.event["comment"]["body"] = f"/pullup server-readiness {SHA}"
            if change == "sender":
                api.event["sender"]["id"] = 99
            if change == "sha":
                api.pr["head"]["sha"] = "b" * 40
            if change == "workflow":
                api.runtime["workflow_ref"] = api.runtime["workflow_ref"].replace(
                    "@refs/heads/main", "@refs/heads/evil"
                )
            with self.assertRaises(t.Refused):
                api.run()
            self.assertFalse(api.dispatched())

    def test_shell_and_receipt_misuse_rejected(self):
        for body in [
            f"/pullup server-prepare {SHA}; id",
            f"/pullup server-readiness {SHA} ops-10",
            f"/pullup server-receipt {SHA}",
            f"/pullup server-apply {SHA}",
        ]:
            with self.assertRaises(t.Refused):
                t.command(body)
        self.assertEqual(
            t.command(f"/pullup server-receipt {SHA} ops-10")[3]["operation_id"], "ops-10"
        )

    def test_uncertain_dispatch_is_not_replayed(self):
        api = API()
        api.event["comment"]["body"] = f"/pullup server-readiness {SHA}"
        api.fail = "actions/workflows/server-control.yml/dispatches"
        with self.assertRaises(TimeoutError):
            api.run()
        api.fail = None
        self.assertIn("duplicate", api.run())
        self.assertEqual(len(api.dispatched()), 1)

    def test_mutating_control_operations_require_existing_full_gates(self):
        for op in ["server-prepare", "server-restore"]:
            called = []
            old = t.green_checks
            try:
                t.green_checks = lambda api, sha, called=called: called.append(sha)
                t.release_gates(None, op, SHA, {})
            finally:
                t.green_checks = old
            self.assertEqual(called, [SHA])
