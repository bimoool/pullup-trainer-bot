"""No database, credentials, network or server required."""

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from tools.cloud_control import main, plan


class CloudControlTests(unittest.TestCase):
    def test_preflight_cannot_start_or_converge(self):
        method, endpoint, body = plan(["staging-preflight", "--sha", "a" * 40])
        self.assertEqual(method, "POST")
        self.assertTrue(endpoint.endswith("/deploy-staging-guarded.yml/dispatches"))
        self.assertEqual(
            body,
            {
                "ref": "main",
                "inputs": {"sha": "a" * 40, "converge": "preflight", "start": "no", "users": "-"},
            },
        )

    def test_qa_never_resets_existing_identities(self):
        _, endpoint, body = plan(["staging-qa"])
        self.assertTrue(endpoint.endswith("/staging-qa.yml/dispatches"))
        self.assertIs(body["inputs"]["reprovision"], False)
        self.assertEqual(body["inputs"]["journeys"], "all")

    def test_rejects_arbitrary_commands_and_refs(self):
        for args in (
            ["production-apply"],
            ["staging-preflight", "--sha", "main"],
            ["status", "1/../../secrets"],
            ["staging-qa", "--ref", "evil"],
        ):
            with (
                self.subTest(args=args),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                plan(args)

    @patch("tools.cloud_control.subprocess.run")
    @patch.dict("os.environ", {}, clear=True)
    def test_missing_binding_never_makes_request(self, run):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["access-check"]), 2)
        run.assert_not_called()

    @patch.dict("os.environ", {"PULLUP_ACTIONS_TOKEN": "synthetic-secret"}, clear=True)
    @patch("tools.cloud_control.subprocess.run")
    def test_secret_not_passed_in_arguments_or_payload(self, run):
        run.return_value.returncode = 0
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["staging-qa"]), 0)
        args, kwargs = run.call_args
        self.assertNotIn("synthetic-secret", json.dumps(args))
        self.assertNotIn("synthetic-secret", kwargs["input"])
        self.assertEqual(kwargs["env"]["GH_TOKEN"], "synthetic-secret")

    @patch.dict("os.environ", {"PULLUP_ACTIONS_TOKEN": "synthetic-secret"}, clear=True)
    @patch("tools.cloud_control.subprocess.run")
    def test_failed_dispatch_is_not_retried_or_reported_success(self, run):
        run.return_value.returncode = 1
        run.return_value.stderr = "synthetic-secret"
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertEqual(main(["staging-qa"]), 2)
        self.assertNotIn("synthetic-secret", output.getvalue())
        self.assertNotIn("accepted", output.getvalue())
        run.assert_called_once()
