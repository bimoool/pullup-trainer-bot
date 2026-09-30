"""Security/batch regression tests for the GitHub owner UI; no network/database."""
import datetime as dt
import importlib.util
import sys
import unittest
from pathlib import Path

for name in ("orch", "orch_control"):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
control = sys.modules["orch_control"]
orch = sys.modules["orch"]


class OwnerControlTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 9, 30, 12, tzinfo=dt.UTC)
        self.issue = {"number": 230, "state": "open", "labels": []}
        self.comment = {"user": {"login": "bimoool"}, "body": "/orch start", "created_at": "2026-09-30T11:59:00Z", "updated_at": "2026-09-30T11:59:00Z", "issue_url": "https://api.github.com/repos/bimoool/pullup-trainer-bot/issues/230"}
        self.state = orch.default_state()

    def auth(self, base="develop/current"):
        return control.authorize(self.comment, self.issue, base, self.now)

    def test_owner_only(self):
        self.assertEqual(self.auth(), "start")
        for login in ("collaborator", "github-actions[bot]", "BIMO OOL"):
            self.comment["user"]["login"] = login
            with self.assertRaises(ValueError):
                self.auth()

    def test_no_shell_or_free_form_targets(self):
        for body in ("/orch start; touch /tmp/pwn", "/orch start main", "/orch start\nwhoami", "/orch start $(id)", "/orch sandbox-start other"):
            self.comment["body"] = body
            with self.assertRaises(ValueError):
                self.auth()
        self.comment["body"] = "/orch start"
        for base in ("main", "production", control.SANDBOX):
            with self.assertRaises(ValueError):
                self.auth(base)

    def test_location_edit_expiry_and_pr(self):
        for key, val in (("updated_at", "2026-09-30T12:00:00Z"), ("issue_url", "https://api.github.com/repos/evil/repo/issues/230"), ("created_at", "2020-01-01T00:00:00Z")):
            old = self.comment[key]
            self.comment[key] = val
            with self.assertRaises(ValueError):
                self.auth()
            self.comment[key] = old
        self.comment["created_at"] = self.comment["updated_at"] = "2020-01-01T00:00:00Z"
        with self.assertRaises(ValueError):
            self.auth()
        self.comment["created_at"] = self.comment["updated_at"] = "2026-09-30T11:59:00Z"
        self.issue["pull_request"] = {"url": "pr"}
        with self.assertRaises(ValueError):
            self.auth()

    def test_approve_only_non_active_canonical_task(self):
        self.issue["number"] = 250
        self.comment["issue_url"] = self.comment["issue_url"].replace("230", "250")
        self.comment["body"] = "/orch approve"
        self.assertEqual(self.auth(), "approve")
        for label in ("orch:test", "orch:dashboard", "status:in-progress", "status:done"):
            self.issue["labels"] = [{"name": label}]
            with self.assertRaises(ValueError):
                self.auth()

    def test_replay_and_running_start_preserve_counters(self):
        self.assertTrue(control.transition(self.state, "start", 10, False))
        self.state["batch"]["completed"] = [235]
        self.state["batch"]["attempts"] = [235, 235]
        self.assertTrue(control.transition(self.state, "start", 11, False))
        self.assertEqual(self.state["batch"]["id"], 1)
        self.assertEqual(self.state["batch"]["attempts"], [235, 235])
        self.assertFalse(control.transition(self.state, "start", 10, False))
        control.transition(self.state, "stop", 12, True)
        self.assertEqual(self.state["batch"]["status"], "stopped")
        self.assertFalse(control.transition(self.state, "start", 11, False))

    def test_active_worker_prevents_new_batch(self):
        control.transition(self.state, "start", 10, True)
        self.assertEqual(self.state["batch"]["status"], "idle")
        self.assertEqual(self.state["batch"]["id"], 0)

    def test_limit_and_attempt_caps(self):
        for field, value in (("limit", 6), ("max_attempts", 9)):
            state = orch.default_state()
            state["batch"][field] = value
            with self.assertRaises(ValueError):
                control.transition(state, "start", 10, False)
        control.transition(self.state, "start", 10, False)
        for n in range(5):
            orch.batch_record(self.state, n, "done")
        self.assertEqual(self.state["batch"]["status"], "owner-review")
        self.assertFalse(orch.batch_can_start(self.state)[0])

    def test_sandbox_fixed_target(self):
        self.comment["body"] = "/orch sandbox-start"
        self.assertEqual(self.auth(control.SANDBOX), "start")
        with self.assertRaises(ValueError):
            self.auth("orch-sandbox/other")


if __name__ == "__main__":
    unittest.main()
