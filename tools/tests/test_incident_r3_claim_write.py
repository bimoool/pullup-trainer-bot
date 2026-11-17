"""PR claim permissions, bounded 403 metadata, and conservative manual reservation denial."""

import copy
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guarded_comment_dispatch as d
import incident_r3_recovery as incident
import incident_r3_recovery_client as client
from incident_diagnostics import Trace

from tools.tests.test_incident_r3_once_recovery import RecoveryAPI
from tools.tests.test_incident_r3_recovery import IncidentAPI

ROOT = Path(__file__).resolve().parents[2]
MANUAL_MARKER = f"<!-- pullup-incident-r3-manual-execution-reserved-v1:{incident.FAILED_RUN} -->"
MANUAL_BODY = (
    f"{MANUAL_MARKER}\nMANUAL R3 EXECUTION RESERVED {incident.CANDIDATE} "
    f"{incident.ORIGINAL_REQUEST} {incident.CONFIRM}"
)


class PermissionTests(unittest.TestCase):
    def test_all_pr_execution_claim_writers_explicitly_grant_pr_write(self):
        # Issue comments on PR conversations need explicit PR comment capability.
        # Align rollback with both established adapters; this is a config contract,
        # not a claim that every historical 403 was caused by this permission.
        for workflow in (
            "production-rollback.yml",
            "cloud-command-dispatch.yml",
            "server-control.yml",
        ):
            text = (ROOT / ".github/workflows" / workflow).read_text()
            permissions = text.split("\npermissions:\n", 1)[1].split("\n\n", 1)[0]
            with self.subTest(workflow=workflow):
                self.assertIn("  pull-requests: write", permissions)
                self.assertIn("  issues: write", permissions)
        rollback = (ROOT / ".github/workflows/production-rollback.yml").read_text()
        self.assertIn("  contents: read", rollback)
        self.assertIn("  actions: read", rollback)


class HttpPrivacyTests(unittest.TestCase):
    def report(self, message, headers=None, raw=None):
        payload = (
            json.dumps({"message": message, "private": "secret https://private/token"}).encode()
            if raw is None
            else raw
        )
        exc = urllib.error.HTTPError(
            "https://private/token", 403, "secret", headers or {}, io.BytesIO(payload)
        )
        trace = Trace()
        trace.before("POST", "issues/399/comments")
        result = json.loads(trace.report(exc))
        text = json.dumps(result)
        self.assertNotIn("secret", text)
        self.assertNotIn("https", text)
        self.assertNotIn("private", text)
        self.assertEqual(result["http_status"], 403)
        self.assertEqual(result["stage"], "CLAIM_WRITE")
        self.assertEqual(result["historical_cause"], "UNKNOWN")
        return result

    def test_known_403_message_classification_and_numeric_header_allowlist(self):
        result = self.report(
            "Resource not accessible by integration",
            {
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "1794750000",
                "X-RateLimit-Limit": "5000",
                "Retry-After": "60",
                "Authorization": "secret",
                "X-GitHub-Request-Id": "secret",
            },
        )
        self.assertEqual(result["http_reason"], "INTEGRATION_ACCESS_DENIED")
        self.assertEqual(
            result["http_limits"],
            {"remaining": 0, "reset": 1794750000, "limit": 5000, "retry_after": 60},
        )
        self.assertEqual(
            self.report("Resource not accessible by personal access token")["http_reason"],
            "TOKEN_ACCESS_DENIED",
        )
        self.assertEqual(self.report("API rate limit exceeded")["http_reason"], "RATE_LIMIT")

    def test_unknown_malformed_oversized_and_injected_responses_are_not_rendered(self):
        for raw in (
            b'{"message":"secret https://private/token"}',
            b"not JSON secret",
            b"[" + b"0," * 5000 + b"0]",
            b'{"message": {"secret": "private"}}',
            b"[" * 1200 + b"0" + b"]" * 1200,
        ):
            with self.subTest(raw_length=len(raw)):
                self.assertEqual(self.report(None, raw=raw)["http_reason"], "UNKNOWN")
        result = self.report(
            "Resource not accessible by integration; secret",
            {
                "Retry-After": "https://private",
                "X-RateLimit-Remaining": "-1",
                "X-RateLimit-Reset": "9" * 100,
                "X-RateLimit-Limit": "1\nsecret",
            },
        )
        self.assertEqual(result["http_reason"], "UNKNOWN")
        self.assertEqual(result["http_limits"], {})

    def test_response_body_read_is_bounded_and_read_failure_is_private(self):
        class Recording(io.BytesIO):
            def __init__(self, data):
                super().__init__(data)
                self.requested = []

            def read(self, size=-1):
                self.requested.append(size)
                return super().read(size)

        stream = Recording(b"x" * 10000)
        exc = urllib.error.HTTPError("https://private/token", 403, "secret", {}, stream)
        result = json.loads(Trace().report(exc))
        self.assertEqual(stream.requested, [4097])
        self.assertEqual(result["http_reason"], "UNKNOWN")

        class Broken:
            def close(self):
                pass

            def read(self, size=-1):
                raise OSError("secret https://private/token")

        exc = urllib.error.HTTPError("https://private/token", 403, "secret", {}, Broken())
        self.assertEqual(json.loads(Trace().report(exc))["http_reason"], "UNKNOWN")

    def test_other_http_status_does_not_read_or_classify_response_body(self):
        stream = io.BytesIO(b'{"message":"Resource not accessible by integration"}')
        exc = urllib.error.HTTPError("https://private/token", 401, "secret", {}, stream)
        result = json.loads(Trace().report(exc))
        self.assertEqual(stream.tell(), 0)
        self.assertEqual(result["http_reason"], "UNKNOWN")
        self.assertEqual(result["http_limits"], {})


class ManualReservationTests(unittest.TestCase):
    def reservation(self, a, body=MANUAL_BODY):
        return {
            "id": 99,
            "body": body,
            "issue_url": f"https://api.github.com/repos/{d.REPO}/issues/399",
            "user": {"id": 1, "login": "bimoool", "type": "User"},
            "author_association": "OWNER",
        }

    def test_owner_actual_reservation_blocks_original_and_recovery_dispatch(self):
        for api_type in (IncidentAPI, RecoveryAPI):
            a = api_type()
            a.comments.append(self.reservation(a))
            with self.subTest(api=api_type.__name__), self.assertRaises(d.Refused):
                a.run()
            self.assertFalse(any(call[0] == "POST" for call in a.calls))

    def test_owner_actual_reservation_blocks_child_before_claim(self):
        a = RecoveryAPI()
        a.run()
        a.comments.append(self.reservation(a))
        before = copy.deepcopy(a.comments)
        with self.assertRaises(d.Refused):
            client.authorize_execution(a, a.env())
        self.assertEqual(a.comments, before)

    def test_proposals_and_other_authors_do_not_falsely_reserve_execution(self):
        for case in ("proposal", "bot", "different_owner", "wrong_pr", "marker_only"):
            a = RecoveryAPI()
            row = self.reservation(a)
            if case == "proposal":
                row["body"] = "Proposal only. No manual execution reserved.\n" + MANUAL_BODY
            if case == "bot":
                row["user"] = {"id": d.BOT_ID, "login": "github-actions[bot]", "type": "Bot"}
            if case == "different_owner":
                row["user"]["id"] = 999
            if case == "wrong_pr":
                row["issue_url"] += "0"
            if case == "marker_only":
                row["body"] = MANUAL_MARKER
            a.comments.append(row)
            with self.subTest(case=case):
                self.assertIn("accepted", a.run())
                client.authorize_execution(a, a.env())

    def test_owner_reservation_before_child_final_refresh_denies(self):
        a = RecoveryAPI()
        a.run()
        original = a.__call__
        listings = 0

        def race(method, path, body=None):
            nonlocal listings
            result = original(method, path, body)
            if method == "GET" and "/comments?" in path:
                listings += 1
                if listings == 2:
                    a.comments.append(self.reservation(a))
            return result

        with self.assertRaises(d.Refused):
            client.authorize_execution(race, a.env())
        self.assertFalse(any(incident.EXECUTION_MARKER in row["body"] for row in a.comments))

    def test_new_owner_reservation_between_dispatch_claim_and_dispatch_denies(self):
        a = RecoveryAPI()
        original = a.__call__

        def race(method, path, body=None):
            result = original(method, path, body)
            if method == "POST" and path == "issues/399/comments":
                a.comments.append(self.reservation(a))
            return result

        with self.assertRaises(d.Refused):
            d.dispatch(a.event, a.runtime, race)
        self.assertFalse(a.dispatched())
