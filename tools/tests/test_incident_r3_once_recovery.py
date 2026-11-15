"""Synthetic delivery recovery; historical HTTP cause remains UNKNOWN."""

import copy
import io
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guarded_comment_dispatch as d
import incident_r3_recovery as i
import incident_r3_recovery_client as client

from tools.tests.test_incident_r3_recovery import COMMAND, CONFIRM, SHA, IncidentAPI

ORIGINAL_REQUEST = 6895994270
ORIGINAL_DISPATCHER = 43724033626
REFUSED_RUN = 43724053051
REFUSED_JOB = 132841996080
ORIGINAL_HEAD = "226c505956a30a720e585c4aa723cd936a408f2a"
RECOVER = f"/pullup incident-r3-recover {SHA} {CONFIRM} {ORIGINAL_REQUEST} {ORIGINAL_DISPATCHER} {REFUSED_RUN}"
RECOVERY_MARKER = f"<!-- pullup-incident-r3-recovery-v1:{REFUSED_RUN} -->"


class RecoveryAPI(IncidentAPI):
    def __init__(self):
        super().__init__()
        self.runtime["sha"] = "f" * 40
        self.original = copy.deepcopy(self.event["comment"])
        self.original.update(id=ORIGINAL_REQUEST, body=COMMAND)
        self.event["comment"].update(id=11, body=RECOVER)
        owner = {"id": 1, "login": "bimoool"}
        bot = {"id": d.BOT_ID, "login": "github-actions[bot]"}
        for run_id, workflow, event, actor, head, status, conclusion in (
            (
                ORIGINAL_DISPATCHER,
                d.DISPATCHER,
                "issue_comment",
                owner,
                ORIGINAL_HEAD,
                "completed",
                "success",
            ),
            (
                REFUSED_RUN,
                i.WORKFLOW,
                "workflow_dispatch",
                bot,
                ORIGINAL_HEAD,
                "completed",
                "failure",
            ),
            (500, d.DISPATCHER, "issue_comment", owner, "f" * 40, "in_progress", None),
            (600, i.WORKFLOW, "workflow_dispatch", bot, "f" * 40, "in_progress", None),
        ):
            self.runs[run_id] = {
                "id": run_id,
                "path": workflow,
                "event": event,
                "actor": actor,
                "triggering_actor": actor,
                "head_sha": head,
                "head_branch": "main",
                "run_attempt": 1,
                "status": status,
                "conclusion": conclusion,
            }
        self.jobs[REFUSED_RUN] = {
            "total_count": 1,
            "jobs": [
                {
                    "id": REFUSED_JOB,
                    "run_id": REFUSED_RUN,
                    "run_attempt": 1,
                    "name": "rollback",
                    "status": "completed",
                    "conclusion": "failure",
                    "steps": [
                        {"name": "Set up job", "status": "completed", "conclusion": "success"},
                        {
                            "name": "Run actions/checkout@v4",
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {"name": "Validate inputs", "status": "completed", "conclusion": "success"},
                        {
                            "name": "Revalidate fixed incident approval and reserve execution before SSH",
                            "status": "completed",
                            "conclusion": "failure",
                        },
                        {
                            "name": "Revalidate R1 owner command and reserve execution before SSH",
                            "status": "completed",
                            "conclusion": "skipped",
                        },
                        {
                            "name": "Guarded rollback R3 apply",
                            "status": "completed",
                            "conclusion": "skipped",
                        },
                        {"name": "Remove key", "status": "completed", "conclusion": "success"},
                        {
                            "name": "Post Run actions/checkout@v4",
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {"name": "Complete job", "status": "completed", "conclusion": "success"},
                    ],
                }
            ],
        }
        self.comments = [
            {
                "id": 21,
                "user": bot,
                "body": i.CLAIM_MARKER
                + "\n"
                + i.request_marker(ORIGINAL_REQUEST, ORIGINAL_DISPATCHER),
            }
        ]

    def __call__(self, method, path, body=None):
        if method == "GET" and path in (
            f"issues/comments/{ORIGINAL_REQUEST}",
            "issues/comments/11",
        ):
            self.calls.append((method, path, body))
            return copy.deepcopy(
                self.original if path.endswith(str(ORIGINAL_REQUEST)) else self.event["comment"]
            )
        return super().__call__(method, path, body)

    def env(self):
        return dict(
            GITHUB_REPOSITORY=d.REPO,
            GITHUB_WORKFLOW_REF=f"{d.REPO}/{i.WORKFLOW}@refs/heads/main",
            GITHUB_REF="refs/heads/main",
            GITHUB_RUN_ATTEMPT="1",
            GITHUB_SHA="f" * 40,
            GITHUB_RUN_ID="600",
            INCIDENT_REQUEST_COMMENT_ID=str(ORIGINAL_REQUEST),
            INCIDENT_DISPATCHER_RUN_ID="500",
            INCIDENT_RECOVERY_COMMENT_ID="11",
            **{k.upper(): v for k, v in i.fixed_inputs().items()},
        )


class RecoveryTests(unittest.TestCase):
    def test_new_capability_routes_same_incident_once_and_reserves_global_execution(self):
        a = RecoveryAPI()
        original = copy.deepcopy(a.comments[0])
        self.assertIn("accepted", a.run())
        payload = a.dispatched()[0][2]
        self.assertEqual(payload["ref"], "main")
        self.assertEqual(payload["inputs"]["incident_request_comment_id"], str(ORIGINAL_REQUEST))
        self.assertEqual(payload["inputs"]["incident_recovery_comment_id"], "11")
        self.assertEqual(a.comments[0], original)
        self.assertIn("duplicate", a.run())
        self.assertEqual(len(a.dispatched()), 1)
        client.authorize_execution(a, a.env())
        self.assertIn(i.EXECUTION_MARKER, a.comments[-1]["body"])
        with self.assertRaises(d.Refused):
            client.authorize_execution(a, a.env())

    def test_unsafe_evidence_refuses_before_any_dispatch_or_claim(self):
        for case in (
            "pending",
            "attempt",
            "job_attempt",
            "job_id",
            "ssh_ran",
            "admission_success",
            "extra_job",
            "extra_step",
            "edited_original",
            "edited_recovery",
            "actor",
            "trigger",
            "old_head",
            "original_claim_missing",
            "original_claim_multiple",
            "execution",
            "fixed_check_attempt",
            "dispatcher_attempt",
            "request",
            "wrong_pr",
        ):
            a = RecoveryAPI()
            job = a.jobs[REFUSED_RUN]["jobs"][0]
            if case == "pending":
                a.runs[REFUSED_RUN]["status"] = "in_progress"
            if case == "attempt":
                a.runs[REFUSED_RUN]["run_attempt"] = 2
            if case == "job_attempt":
                job["run_attempt"] = 2
            if case == "job_id":
                job["id"] += 1
            if case == "ssh_ran":
                job["steps"][5]["conclusion"] = "success"
            if case == "admission_success":
                job["steps"][3]["conclusion"] = "success"
            if case == "extra_job":
                a.jobs[REFUSED_RUN]["jobs"].append(copy.deepcopy(job))
            if case == "extra_step":
                job["steps"].append(
                    {"name": "unknown", "status": "completed", "conclusion": "success"}
                )
            if case == "edited_original":
                a.original["updated_at"] += "edited"
            if case == "edited_recovery":
                a.event["comment"]["updated_at"] += "edited"
            if case == "actor":
                a.runs[REFUSED_RUN]["actor"] = {"id": 1, "login": "bimoool"}
            if case == "trigger":
                a.runs[ORIGINAL_DISPATCHER]["triggering_actor"] = {"id": 99, "login": "other"}
            if case == "old_head":
                a.runs[REFUSED_RUN]["head_sha"] = "a" * 40
            if case == "original_claim_missing":
                a.comments = []
            if case == "original_claim_multiple":
                a.comments *= 2
            if case == "execution":
                a.comments.append(
                    {
                        "id": 22,
                        "user": {"id": d.BOT_ID, "login": "github-actions[bot]"},
                        "body": i.EXECUTION_MARKER,
                    }
                )
            if case == "fixed_check_attempt":
                a.runs[i.CHECK_RUN]["run_attempt"] = 2
            if case == "dispatcher_attempt":
                a.runtime["run_attempt"] = "2"
            if case == "request":
                a.event["comment"]["body"] = RECOVER.replace(str(ORIGINAL_REQUEST), "999")
            if case == "wrong_pr":
                a.event["issue"]["number"] = 400
            with self.subTest(case=case), self.assertRaises(d.Refused):
                a.run()
            self.assertFalse(a.dispatched())
            self.assertFalse(any(c[0] == "POST" for c in a.calls))

    def test_child_revalidates_changed_evidence_claims_and_current_provenance(self):
        for case in (
            "ssh",
            "execution",
            "multiple_recovery",
            "missing_recovery",
            "wrong_binding",
            "new_actor",
            "new_attempt",
            "edited_recovery",
            "original_id",
            "new_dispatcher",
        ):
            a = RecoveryAPI()
            a.run()
            env = a.env()
            if case == "ssh":
                a.jobs[REFUSED_RUN]["jobs"][0]["steps"][5]["conclusion"] = "success"
            if case == "execution":
                a.comments.append(
                    {
                        "user": {"id": d.BOT_ID, "login": "github-actions[bot]"},
                        "body": i.EXECUTION_MARKER,
                    }
                )
            if case == "multiple_recovery":
                a.comments.append(copy.deepcopy(a.comments[-1]))
            if case == "missing_recovery":
                a.comments.pop()
            if case == "wrong_binding":
                a.comments[-1]["body"] = a.comments[-1]["body"].replace(":11:500", ":12:500")
            if case == "new_actor":
                a.runs[600]["actor"] = {"id": 1, "login": "bimoool"}
            if case == "new_attempt":
                env["GITHUB_RUN_ATTEMPT"] = "2"
            if case == "edited_recovery":
                a.event["comment"]["updated_at"] += "edited"
            if case == "original_id":
                env["INCIDENT_REQUEST_COMMENT_ID"] = "10"
            if case == "new_dispatcher":
                env["INCIDENT_DISPATCHER_RUN_ID"] = str(ORIGINAL_DISPATCHER)
            before = copy.deepcopy(a.comments)
            with self.subTest(case=case), self.assertRaises(d.Refused):
                client.authorize_execution(a, env)
            self.assertEqual(a.comments, before)

    def test_uncertain_dispatch_and_execution_posts_never_replay(self):
        for target in ("dispatch_claim", "dispatch", "execution_claim"):
            a = RecoveryAPI()
            if target == "execution_claim":
                a.run()
            original = a.__call__

            def uncertain(method, path, body=None, original=original, target=target):
                result = original(method, path, body)
                if method == "POST" and (
                    (target == "dispatch" and path.endswith("/dispatches"))
                    or (target != "dispatch" and path == "issues/399/comments")
                ):
                    raise TimeoutError("secret body URL must never be logged")
                return result

            with self.subTest(target=target), self.assertRaises(TimeoutError):
                if target == "execution_claim":
                    client.authorize_execution(uncertain, a.env())
                else:
                    d.dispatch(a.event, a.runtime, uncertain)
            if target == "execution_claim":
                with self.assertRaises(d.Refused):
                    client.authorize_execution(a, a.env())
            else:
                self.assertIn("duplicate", a.run())
            self.assertLessEqual(len(a.dispatched()), 1)

    def test_changed_original_between_claim_and_dispatch_stops(self):
        a = RecoveryAPI()
        original = a.__call__

        def race(method, path, body=None):
            result = original(method, path, body)
            if method == "POST" and path == "issues/399/comments":
                a.jobs[REFUSED_RUN]["jobs"][0]["steps"][5]["conclusion"] = "success"
            return result

        with self.assertRaises(d.Refused):
            d.dispatch(a.event, a.runtime, race)
        self.assertFalse(a.dispatched())
        self.assertTrue(any(RECOVERY_MARKER in c["body"] for c in a.comments))

    def test_child_refreshes_recovery_approval_and_claim_before_reservation(self):
        for case in ("claim_disappeared", "approval_edited", "ssh_changed"):
            a = RecoveryAPI()
            a.run()
            original = a.__call__
            listings = 0

            def race(method, path, body=None, original=original, case=case, a=a):
                nonlocal listings
                result = original(method, path, body)
                if method == "GET" and "/comments?" in path:
                    listings += 1
                    if listings == 2:
                        if case == "claim_disappeared":
                            a.comments.pop()
                        elif case == "approval_edited":
                            a.event["comment"]["updated_at"] += "edited"
                        else:
                            a.jobs[REFUSED_RUN]["jobs"][0]["steps"][5]["conclusion"] = "success"
                return result

            with self.subTest(case=case), self.assertRaises(d.Refused):
                client.authorize_execution(race, a.env())
            self.assertFalse(any(i.EXECUTION_MARKER in c["body"] for c in a.comments))

    def test_same_production_concurrency_and_single_reservation_precede_ssh(self):

        text = (
            Path(__file__).resolve().parents[2] / ".github/workflows/production-rollback.yml"
        ).read_text()
        self.assertIn("group: production", text)
        self.assertIn("INCIDENT_RECOVERY_COMMENT_ID:", text)
        self.assertLess(
            text.index("python3 tools/incident_r3_recovery_client.py"), text.index("ssh -i")
        )


class DiagnosticTests(unittest.TestCase):
    def test_allowlisted_failure_output_never_renders_exception_or_url(self):
        for exc in (
            d.Refused("attacker secret https://private/token"),
            urllib.error.HTTPError("https://private/token", 403, "secret", {}, None),
            TimeoutError("secret"),
            KeyError("secret"),
        ):
            output = io.StringIO()
            with patch.object(client, "main", side_effect=exc), redirect_stdout(output):
                self.assertEqual(client.run(), 1)
            value = output.getvalue()
            self.assertNotIn("secret", value)
            self.assertNotIn("https", value)
            self.assertIn("UNKNOWN", value) if isinstance(exc, d.Refused) else None
            if isinstance(exc, urllib.error.HTTPError):
                self.assertIn("403", value)
