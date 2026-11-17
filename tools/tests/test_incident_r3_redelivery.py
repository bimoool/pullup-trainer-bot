"""One fixed failed-before-SSH redelivery; no arbitrary retries or log-derived privileges."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guarded_comment_dispatch as d
import incident_r3_recovery as i
import incident_r3_recovery_client as client

from tools.tests.test_incident_r3_once_recovery import RecoveryAPI
from tools.tests.test_incident_r3_recovery import IncidentAPI

PARENT_REQUEST = 6896948857
PARENT_DISPATCHER = 43730724401
PARENT_RUN = 43730752868
PARENT_JOB = 132862408612
PARENT_HEAD = "f6bf15dafa03dd1aa74c4353d7099a8b3563c9e7"
COMMAND = f"/pullup incident-r3-redeliver {i.CANDIDATE} {i.CONFIRM} {i.ORIGINAL_REQUEST} {PARENT_REQUEST} {PARENT_DISPATCHER} {PARENT_RUN}"
MARKER = f"<!-- pullup-incident-r3-redelivery-v1:{PARENT_RUN} -->"


class RedeliveryAPI(RecoveryAPI):
    def __init__(self):
        super().__init__()
        self.parent = copy.deepcopy(self.event["comment"])
        self.parent.update(id=PARENT_REQUEST, body=i.RECOVERY_COMMAND)
        self.event["comment"].update(id=12, body=COMMAND)
        self.runs[PARENT_DISPATCHER] = dict(
            self.runs[500],
            id=PARENT_DISPATCHER,
            head_sha=PARENT_HEAD,
            status="completed",
            conclusion="success",
        )
        self.runs[PARENT_RUN] = dict(
            self.runs[600],
            id=PARENT_RUN,
            head_sha=PARENT_HEAD,
            status="completed",
            conclusion="failure",
        )
        self.jobs[PARENT_RUN] = copy.deepcopy(self.jobs[i.REFUSED_RUN])
        self.jobs[PARENT_RUN]["jobs"][0].update(id=PARENT_JOB, run_id=PARENT_RUN)
        self.comments.append(
            {
                "id": 22,
                "user": {"id": d.BOT_ID, "login": "github-actions[bot]"},
                "body": i.RECOVERY_MARKER
                + "\n"
                + i.recovery_marker(PARENT_REQUEST, PARENT_DISPATCHER),
            }
        )

    def __call__(self, method, path, body=None):
        if method == "GET" and path in (f"issues/comments/{PARENT_REQUEST}", "issues/comments/12"):
            self.calls.append((method, path, body))
            return copy.deepcopy(
                self.parent if path.endswith(str(PARENT_REQUEST)) else self.event["comment"]
            )
        return super().__call__(method, path, body)

    def env(self):
        env = super().env()
        env.update(
            INCIDENT_RECOVERY_COMMENT_ID=str(PARENT_REQUEST), INCIDENT_REDELIVERY_COMMENT_ID="12"
        )
        return env


class RedeliveryTests(unittest.TestCase):
    def test_fixed_second_delivery_preserves_both_claims_and_same_global_execution(self):
        a = RedeliveryAPI()
        old = copy.deepcopy(a.comments)
        self.assertIn("accepted", a.run())
        self.assertEqual(a.comments[:2], old)
        self.assertIn(MARKER, a.comments[-1]["body"])
        inputs = a.dispatched()[0][2]["inputs"]
        self.assertEqual(inputs["incident_request_comment_id"], str(i.ORIGINAL_REQUEST))
        self.assertEqual(inputs["incident_recovery_comment_id"], str(PARENT_REQUEST))
        self.assertEqual(inputs["incident_redelivery_comment_id"], "12")
        self.assertEqual({k: inputs[k] for k in i.fixed_inputs()}, i.fixed_inputs())
        self.assertIn("duplicate", a.run())
        client.authorize_execution(a, a.env())
        self.assertIn(i.EXECUTION_MARKER, a.comments[-1]["body"])
        with self.assertRaises(d.Refused):
            client.authorize_execution(a, a.env())
        self.assertEqual(len(a.dispatched()), 1)
        self.assertFalse(any("/logs" in call[1] for call in a.calls))

    def test_changed_chain_refuses_before_new_claim_or_dispatch(self):
        for case in (
            "pending",
            "parent_attempt",
            "job_attempt",
            "job_id",
            "extra_job",
            "ssh",
            "admission",
            "head",
            "actor",
            "parent_dispatch_actor",
            "parent_dispatch_attempt",
            "edited_parent",
            "missing_parent_claim",
            "duplicate_parent_claim",
            "wrong_parent_binding",
            "new_edited",
            "new_actor",
            "new_attempt",
            "fixed_check",
            "global_execution",
            "manual",
            "duplicate_redelivery",
            "near_command",
            "parent_comment_id",
            "parent_owner",
            "parent_body",
            "parent_dispatch_head",
            "parent_run_id",
            "extra_step",
            "new_head",
            "new_trigger",
        ):
            a = RedeliveryAPI()
            job = a.jobs[PARENT_RUN]["jobs"][0]
            if case == "parent_comment_id":
                a.parent["id"] += 1
            if case == "parent_owner":
                a.parent["user"]["id"] = 99
            if case == "parent_body":
                a.parent["body"] += " extra"
            if case == "parent_dispatch_head":
                a.runs[PARENT_DISPATCHER]["head_sha"] = "0" * 40
            if case == "parent_run_id":
                a.runs[PARENT_RUN]["id"] += 1
            if case == "extra_step":
                job["steps"].append(
                    {"name": "unknown", "status": "completed", "conclusion": "success"}
                )
            if case == "new_head":
                a.runs[500]["head_sha"] = "0" * 40
            if case == "new_trigger":
                a.runs[500]["triggering_actor"] = {"id": 99, "login": "other"}
            if case == "pending":
                a.runs[PARENT_RUN]["status"] = "in_progress"
            if case == "parent_attempt":
                a.runs[PARENT_RUN]["run_attempt"] = 2
            if case == "job_attempt":
                job["run_attempt"] = 2
            if case == "job_id":
                job["id"] += 1
            if case == "extra_job":
                a.jobs[PARENT_RUN]["jobs"].append(copy.deepcopy(job))
            if case == "ssh":
                job["steps"][5]["conclusion"] = "success"
            if case == "admission":
                job["steps"][3]["conclusion"] = "success"
            if case == "head":
                a.runs[PARENT_RUN]["head_sha"] = "0" * 40
            if case == "actor":
                a.runs[PARENT_RUN]["actor"] = {"id": 1, "login": "bimoool"}
            if case == "parent_dispatch_actor":
                a.runs[PARENT_DISPATCHER]["actor"] = {
                    "id": d.BOT_ID,
                    "login": "github-actions[bot]",
                }
            if case == "parent_dispatch_attempt":
                a.runs[PARENT_DISPATCHER]["run_attempt"] = 2
            if case == "edited_parent":
                a.parent["updated_at"] += "edited"
            if case == "missing_parent_claim":
                a.comments.pop()
            if case == "duplicate_parent_claim":
                a.comments.append(copy.deepcopy(a.comments[-1]))
            if case == "wrong_parent_binding":
                a.comments[-1]["body"] = a.comments[-1]["body"].replace(str(PARENT_REQUEST), "999")
            if case == "new_edited":
                a.event["comment"]["updated_at"] += "edited"
            if case == "new_actor":
                a.runs[500]["actor"] = {"id": 99, "login": "other"}
            if case == "new_attempt":
                a.runtime["run_attempt"] = "2"
            if case == "fixed_check":
                a.runs[i.CHECK_RUN]["run_attempt"] = 2
            if case == "global_execution":
                a.comments.append(
                    {
                        "user": {"id": d.BOT_ID, "login": "github-actions[bot]"},
                        "body": i.EXECUTION_MARKER,
                    }
                )
            if case == "manual":
                a.comments.append(
                    {
                        "user": {"id": 1, "login": "bimoool", "type": "User"},
                        "body": i.MANUAL_EXECUTION_RESERVATION,
                        "author_association": "OWNER",
                        "issue_url": f"https://api.github.com/repos/{d.REPO}/issues/399",
                    }
                )
            if case == "duplicate_redelivery":
                a.comments.extend(
                    [{"user": {"id": d.BOT_ID, "login": "github-actions[bot]"}, "body": MARKER}] * 2
                )
            if case == "near_command":
                a.event["comment"]["body"] = COMMAND + " extra"
            with self.subTest(case=case), self.assertRaises(d.Refused):
                a.run()
            self.assertFalse(any(c[0] == "POST" for c in a.calls))

    def test_child_requires_current_provenance_and_its_own_claim(self):
        for case in (
            "missing_new",
            "wrong_new",
            "duplicate_new",
            "edited_new",
            "new_actor",
            "new_attempt",
            "parent_edited",
            "parent_job",
            "parent_request",
            "manual",
            "new_head",
            "new_trigger",
        ):
            a = RedeliveryAPI()
            a.run()
            env = a.env()
            if case == "missing_new":
                a.comments.pop()
            if case == "wrong_new":
                a.comments[-1]["body"] = a.comments[-1]["body"].replace(":12:500", ":13:500")
            if case == "duplicate_new":
                a.comments.append(copy.deepcopy(a.comments[-1]))
            if case == "edited_new":
                a.event["comment"]["updated_at"] += "edited"
            if case == "new_head":
                a.runs[600]["head_sha"] = "0" * 40
            if case == "new_trigger":
                a.runs[600]["triggering_actor"] = {"id": 99, "login": "other"}
            if case == "new_actor":
                a.runs[600]["actor"] = {"id": 1, "login": "bimoool"}
            if case == "new_attempt":
                env["GITHUB_RUN_ATTEMPT"] = "2"
            if case == "parent_edited":
                a.parent["updated_at"] += "edited"
            if case == "parent_job":
                a.jobs[PARENT_RUN]["jobs"][0]["id"] += 1
            if case == "parent_request":
                env["INCIDENT_RECOVERY_COMMENT_ID"] = "11"
            if case == "manual":
                a.comments.append(
                    {
                        "user": {"id": 1, "login": "bimoool", "type": "User"},
                        "body": i.MANUAL_EXECUTION_RESERVATION,
                        "author_association": "OWNER",
                        "issue_url": f"https://api.github.com/repos/{d.REPO}/issues/399",
                    }
                )
            before = copy.deepcopy(a.comments)
            with self.subTest(case=case), self.assertRaises(d.Refused):
                client.authorize_execution(a, env)
            self.assertEqual(a.comments, before)

    def test_old_incident_routes_deny_new_redelivery_claim(self):
        for api_type in (IncidentAPI, RecoveryAPI):
            a = api_type()
            a.comments.append(
                {"user": {"id": d.BOT_ID, "login": "github-actions[bot]"}, "body": MARKER}
            )
            with self.subTest(api=api_type.__name__), self.assertRaises(d.Refused):
                a.run()
            self.assertFalse(a.dispatched())

    def test_old_children_also_deny_second_delivery_reservation(self):
        from tools.tests.test_incident_r3_recovery import ExecutionTests

        c, original_api, env = ExecutionTests().fixture()
        recovery_api = RecoveryAPI()
        recovery_api.run()
        for a, child_env in ((original_api, env), (recovery_api, recovery_api.env())):
            a.comments.append(
                {"user": {"id": d.BOT_ID, "login": "github-actions[bot]"}, "body": MARKER}
            )
            before = copy.deepcopy(a.comments)
            with self.assertRaises(d.Refused):
                c.authorize_execution(a, child_env)
            self.assertEqual(a.comments, before)

    def test_final_refresh_requires_preserved_parent_claim_and_approval(self):
        for case in ("parent_claim", "parent_approval", "global_execution", "manual"):
            a = RedeliveryAPI()
            a.run()
            original = a.__call__
            parent_jobs = 0

            def race(method, path, body=None, original=original, case=case, a=a):
                nonlocal parent_jobs
                result = original(method, path, body)
                if (
                    method == "GET"
                    and path == f"actions/runs/{PARENT_RUN}/jobs?filter=latest&per_page=100"
                ):
                    parent_jobs += 1
                    if parent_jobs == 2:
                        if case == "parent_claim":
                            a.comments.pop(1)
                        elif case == "parent_approval":
                            a.parent["updated_at"] += "edited"
                        elif case == "global_execution":
                            a.comments.append(
                                {
                                    "user": {"id": d.BOT_ID, "login": "github-actions[bot]"},
                                    "body": i.EXECUTION_MARKER,
                                }
                            )
                        else:
                            a.comments.append(
                                {
                                    "user": {"id": 1, "login": "bimoool", "type": "User"},
                                    "body": i.MANUAL_EXECUTION_RESERVATION,
                                    "author_association": "OWNER",
                                    "issue_url": f"https://api.github.com/repos/{d.REPO}/issues/399",
                                }
                            )
                return result

            with self.subTest(case=case), self.assertRaises(d.Refused):
                client.authorize_execution(race, a.env())
            self.assertFalse(
                any(
                    c[0] == "POST" and i.EXECUTION_MARKER in (c[2] or {}).get("body", "")
                    for c in a.calls
                )
            )

    def test_uncertain_reserved_posts_never_redeliver_or_execute_again(self):
        for target in ("claim", "dispatch", "execution"):
            a = RedeliveryAPI()
            if target == "execution":
                a.run()
            original = a.__call__

            def uncertain(method, path, body=None, original=original, target=target):
                result = original(method, path, body)
                if method == "POST" and (
                    (target == "dispatch" and path.endswith("/dispatches"))
                    or (target != "dispatch" and path == "issues/399/comments")
                ):
                    raise TimeoutError
                return result

            with self.subTest(target=target), self.assertRaises(TimeoutError):
                if target == "execution":
                    client.authorize_execution(uncertain, a.env())
                else:
                    d.dispatch(a.event, a.runtime, uncertain)
            if target == "execution":
                with self.assertRaises(d.Refused):
                    client.authorize_execution(a, a.env())
            else:
                self.assertIn("duplicate", a.run())
            self.assertLessEqual(len(a.dispatched()), 1)

    def test_parent_change_after_claim_keeps_reservation_but_stops_dispatch(self):
        a = RedeliveryAPI()
        original = a.__call__

        def race(method, path, body=None):
            result = original(method, path, body)
            if method == "POST" and path == "issues/399/comments":
                a.parent["updated_at"] += "edited"
            return result

        with self.assertRaises(d.Refused):
            d.dispatch(a.event, a.runtime, race)
        self.assertTrue(any(MARKER in row["body"] for row in a.comments))
        self.assertFalse(a.dispatched())
