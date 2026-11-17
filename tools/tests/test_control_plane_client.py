"""Offline exact owner/workflow/claim binding, including independent recovery."""

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import controller_control_client as c
import current_checks as checks
import guarded_comment_dispatch as dispatch

from tools.tests.check_fixtures import SHA, CheckAPI

MAIN = "d" * 40
OWNER = {"id": 1, "login": "bimoool"}


def comment(identity, text):
    return {
        "id": identity,
        "body": text,
        "issue_url": f"https://api.github.com/repos/{c.REPO}/issues/400",
        "user": dict(OWNER, type="User"),
        "author_association": "OWNER",
        "created_at": "2026-11-15T12:00:00Z",
        "updated_at": "2026-11-15T12:00:00Z",
    }


def run(identity, path, event, actor):
    return {
        "id": identity,
        "repository": {"full_name": c.REPO},
        "path": path,
        "event": event,
        "head_branch": "main",
        "head_sha": MAIN,
        "run_attempt": 1,
        "actor": actor.copy(),
        "triggering_actor": actor.copy(),
        "status": "in_progress",
    }


class API:
    def __init__(self):
        self.checks = CheckAPI()
        self.checks.add(
            "authorization", run_id=108, job_id=1008, workflow="cloud-command-tests.yml"
        )
        self.comments = {
            10: comment(10, f"/pullup server-adopt-controller {SHA}"),
            11: comment(11, f"/pullup server-recover-controller {SHA} ops-10"),
        }
        self.claims = [
            {
                "id": 20,
                "user": c.BOT.copy(),
                "body": f"<!-- pullup-server-adopt-controller-v1:400:{SHA}:ops-10 -->\ndispatcher run 500",
            }
        ]
        self.runs = {
            500: run(500, c.DISPATCHER, "issue_comment", OWNER),
            600: run(600, c.ADOPT_WORKFLOW, "workflow_dispatch", c.BOT),
            700: run(700, c.RECOVERY_WORKFLOW, "issue_comment", OWNER),
        }
        self.pr = {
            "number": 400,
            "state": "open",
            "head": {"sha": SHA, "ref": "codex/controller", "repo": {"full_name": c.REPO}},
            "base": {"ref": "main", "repo": {"full_name": c.REPO}},
        }
        self.fail = None
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == self.fail:
            raise TimeoutError
        if method == "POST":
            row = {"id": 100 + len(self.claims), "user": c.BOT.copy(), "body": body["body"]}
            self.claims.append(row)
            return copy.deepcopy(row)
        if path == "":
            return {"id": 123, "full_name": c.REPO, "default_branch": "main", "owner": OWNER.copy()}
        if path.startswith("issues/comments/"):
            return copy.deepcopy(self.comments[int(path.split("/")[-1])])
        if path.startswith("pulls/"):
            return copy.deepcopy(self.pr)
        if path.startswith("issues/") and "comments?" in path:
            return copy.deepcopy(self.claims)
        if (
            path.startswith("actions/runs/")
            and len(path.split("/")) == 3
            and int(path.split("/")[-1]) in self.runs
        ):
            return copy.deepcopy(self.runs[int(path.split("/")[-1])])
        if path == f"git/commits/{SHA}":
            return {"tree": {"sha": "e" * 40}}
        if path == "commits/main":
            return {"commit": {"tree": {"sha": "e" * 40}}}
        return self.checks(method, path, body)


def env(recovery=False):
    workflow = c.RECOVERY_WORKFLOW if recovery else c.ADOPT_WORKFLOW
    return {
        "GITHUB_REPOSITORY": c.REPO,
        "GITHUB_WORKFLOW_REF": f"{c.REPO}/{workflow}@refs/heads/main",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": MAIN,
        "GITHUB_RUN_ID": "700" if recovery else "600",
        "OPERATION": "adopt",
        "CANDIDATE_SHA": SHA,
        "OPERATION_ID": "ops-10",
        "PR_NUMBER": "400",
        "REQUEST_COMMENT_ID": "10",
    }


def event(api):
    return {
        "action": "created",
        "repository": {"id": 123},
        "issue": {"number": 400, "pull_request": {}},
        "sender": OWNER.copy(),
        "comment": copy.deepcopy(api.comments[11]),
    }


class ClientTests(unittest.TestCase):
    def test_release_cli_defaults_seven_but_controller_eight_is_explicit(self):
        release = {
            "ruff",
            "pytest",
            "frontend build",
            "e2e",
            "codex-review",
            "security",
            "rehearse",
        }
        for arguments, expected in (
            ([], release),
            (["--required", *sorted(release | {"authorization"})], release | {"authorization"}),
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(sys, "argv", ["current_checks.py", SHA, *arguments]),
                patch.object(checks, "ensure_green") as gate,
                patch("builtins.print"),
            ):
                checks.main()
                self.assertEqual(set(gate.call_args.args[2]), expected)

    def test_only_filtered_owner_jobs_reserve_production_concurrency(self):
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/controller-recovery.yml"
        ).read_text()
        before_jobs, jobs = workflow.split("\njobs:\n", 1)
        # GitHub admits workflow-level concurrency before evaluating any job if.
        # Ordinary comments and matching non-owner comments must never evict a
        # pending production operation before live Python admission can run.
        self.assertNotIn("\nconcurrency:", before_jobs)
        self.assertIn("\n    concurrency:\n", jobs)
        condition = jobs.split("    if: >-\n", 1)[1].split("    runs-on:", 1)[0]
        self.assertIn("github.event.comment.user.id == github.event.repository.owner.id", condition)
        self.assertIn("github.event.sender.id == github.event.repository.owner.id", condition)
        self.assertIn("github.event.comment.author_association == 'OWNER'", condition)

    def test_adoption_requires_full_ci_authorization_main_tree_and_dispatcher_provenance(self):
        api = API()
        self.assertEqual(c.authorize_adopt(api, env()), (400, "adopt", SHA, "ops-10", None))
        self.assertEqual(
            dispatch.command(f"/pullup server-adopt-controller {SHA}")[2], "controller-control.yml"
        )
        mutations = (
            lambda a, e: a.checks.checks.pop(),
            lambda a, e: a.checks.checks[-1].update(conclusion="failure"),
            lambda a, e: a.runs[500].update(head_sha="f" * 40),
            lambda a, e: a.runs[600].update(actor=OWNER.copy()),
            lambda a, e: a.runs[600].update(run_attempt=2),
            lambda a, e: e.update(GITHUB_RUN_ATTEMPT="2"),
            lambda a, e: a.comments[10].update(updated_at="2026-11-15T12:01:00Z"),
            lambda a, e: a.pr["head"].update(sha="f" * 40),
            lambda a, e: a.claims.clear(),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                api, environment = API(), env()
                mutate(api, environment)
                with self.assertRaises((c.Refused, c.CheckRefused)):
                    c.authorize_adopt(api, environment)
                self.assertFalse(any(method == "POST" for method, _, _ in api.calls))
        api = API()
        original = api.__call__

        def wrong_tree(method, path, body=None):
            if path == "commits/main":
                return {"commit": {"tree": {"sha": "f" * 40}}}
            return original(method, path, body)

        with self.assertRaises(c.Refused):
            c.authorize_adopt(wrong_tree, env())

    def test_recovery_survives_changed_pr_head_and_failing_product_checks(self):
        api = API()
        api.pr["head"]["sha"] = "f" * 40
        api.pr["state"] = "closed"
        api.checks.checks.clear()
        with patch.dict(
            sys.modules, {"guarded_comment_dispatch": None, "server_control_client": None}
        ):
            self.assertEqual(
                c.authorize_recovery(api, env(True), event(api)),
                (400, "recover", SHA, "ops-11", "ops-10"),
            )
        self.assertFalse(
            any("check-runs" in path or path == "commits/main" for _, path, _ in api.calls)
        )

    def test_recovery_edits_cross_pr_owner_reruns_and_original_binding_refuse(self):
        mutations = (
            lambda a, e, v: a.comments[11].update(updated_at="changed"),
            lambda a, e, v: a.comments[10].update(body=f"/pullup server-prepare {SHA}"),
            lambda a, e, v: a.comments[10].update(
                issue_url=f"https://api.github.com/repos/{c.REPO}/issues/401"
            ),
            lambda a, e, v: v["sender"].update(id=99),
            lambda a, e, v: e.update(
                GITHUB_WORKFLOW_REF=f"{c.REPO}/{c.RECOVERY_WORKFLOW}@refs/heads/evil"
            ),
            lambda a, e, v: a.runs[700].update(triggering_actor=c.BOT.copy()),
            lambda a, e, v: e.update(GITHUB_RUN_ATTEMPT="2"),
        )
        for mutate in mutations:
            api, environment = API(), env(True)
            snapshot = event(api)
            mutate(api, environment, snapshot)
            with self.assertRaises(c.Refused):
                c.authorize_recovery(api, environment, snapshot)

    def test_status_can_query_interrupted_recovery_operation(self):
        api = API()
        api.comments[12] = comment(12, f"/pullup server-controller-status {SHA} ops-11")
        snapshot = event(api)
        snapshot["comment"] = copy.deepcopy(api.comments[12])
        self.assertEqual(
            c.authorize_recovery(api, env(True), snapshot),
            (400, "status", SHA, "ops-11", "ops-11"),
        )

    def test_execution_claim_is_durable_and_not_replayed_after_uncertain_response(self):
        api = API()
        c.reserve_execution(api, 400, "adopt", "ops-10", None, "600")
        with self.assertRaises(c.Refused):
            c.reserve_execution(api, 401, "adopt", "ops-10", None, "601")
        posts = [entry for entry in api.calls if entry[0] == "POST"]
        self.assertEqual(len(posts), 1)
        original = api.__call__

        def lost_response(method, path, body=None):
            result = original(method, path, body)
            if method == "POST":
                raise TimeoutError
            return result

        with self.assertRaises(TimeoutError):
            c.reserve_execution(lost_response, 400, "recover", "ops-11", "ops-10", "700")
        with self.assertRaises(c.Refused):
            c.reserve_execution(api, 400, "recover", "ops-11", "ops-10", "701")

    def test_private_journal_fields_and_unattributed_receipts_never_export(self):
        import json

        record = {"candidate": SHA, "operation_id": "ops-10", "state": "VERIFIED"}
        self.assertEqual(c.safe_receipt(json.dumps(record).encode(), SHA, "ops-10"), record)
        for extra in (
            {"before": {}},
            {"error": "private@example.com"},
            {"operation_id": "ops-11"},
            {"candidate": "f" * 40},
        ):
            with self.assertRaises(c.Refused):
                c.safe_receipt(json.dumps(dict(record, **extra)).encode(), SHA, "ops-10")


if __name__ == "__main__":
    unittest.main()
