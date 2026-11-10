"""Offline authorization and at-most-once failure-path checks."""

import copy
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guarded_comment_dispatch as t

from tools.tests.check_fixtures import CheckAPI

SHA = "a" * 40


class API:
    def __init__(self):
        self.calls, self.comments, self.heads = [], [], []
        self.fail = None
        self.pr = {
            "number": 400,
            "state": "open",
            "head": {"sha": SHA, "ref": "codex/probe", "repo": {"full_name": t.REPO}},
            "base": {"ref": "main", "repo": {"full_name": t.REPO}},
        }
        self.event = {
            "action": "created",
            "repository": {"id": 123, "full_name": t.REPO, "default_branch": "main"},
            "issue": {"number": 400, "pull_request": {}},
            "sender": {"id": 1, "login": "bimoool"},
            "comment": {
                "id": 10,
                "body": f"/pullup staging-preflight {SHA}",
                "author_association": "OWNER",
                "user": {"id": 1, "login": "bimoool", "type": "User"},
            },
        }
        self.runtime = {
            "repository": t.REPO,
            "workflow_ref": f"{t.REPO}/{t.DISPATCHER}@refs/heads/main",
            "run_id": "500",
        }

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if self.fail == path:
            raise TimeoutError
        if method == "GET":
            if path == "":
                return {"id": 123, "owner": {"id": 1, "login": "bimoool"}}
            if path == "issues/comments/10":
                return copy.deepcopy(self.event["comment"])
            if path.startswith("pulls/"):
                pr = copy.deepcopy(self.pr)
                if self.heads:
                    pr["head"]["sha"] = self.heads.pop(0)
                return pr
            if path.startswith("actions/workflows/"):
                return {"path": f".github/workflows/{path.split('/')[2]}", "state": "active"}
            if "/comments?" in path:
                return copy.deepcopy(self.comments)
        if method == "POST" and path == "issues/400/comments":
            claim = {
                "id": 20,
                "body": body["body"],
                "user": {"id": t.BOT_ID, "login": "github-actions[bot]"},
            }
            self.comments.append(claim)
            return claim
        if method == "POST" and path.endswith("/dispatches"):
            return None
        if method == "PATCH":
            self.comments[-1]["body"] = body["body"]
            return self.comments[-1]
        raise AssertionError((method, path))

    def run(self):
        return t.dispatch(self.event, self.runtime, self)

    def dispatched(self):
        return [c for c in self.calls if c[1].endswith("/dispatches")]


class Tests(unittest.TestCase):
    def test_fixed_release_commands(self):
        self.assertEqual(
            t.command(f"/pullup staging-snapshot {SHA}")[2:],
            ("staging-snapshot.yml", {"candidate_sha": SHA}),
        )
        # Recovery observation stays available even when CI or a deployment failed.
        t.release_gates(
            lambda *_: self.fail("snapshot must not depend on CI"), "staging-snapshot", SHA, {}
        )
        self.assertEqual(
            t.command(f"/pullup staging-deploy {SHA}")[3],
            {
                "sha": SHA,
                "converge": "dry-run",
                "start": "yes",
                "users": "-",
            },
        )
        self.assertEqual(t.command(f"/pullup staging-qa {SHA}")[3]["candidate_sha"], SHA)
        self.assertEqual(t.command(f"/pullup staging-qa {SHA}")[2], "release-qa.yml")
        self.assertEqual(t.command(f"/pullup staging-qa {SHA}")[3], {"candidate_sha": SHA})
        self.assertEqual(
            t.command(
                f"/pullup production-apply {SHA} {'b' * 12} {'c' * 12} PRODUCTION-APPLY-{SHA[:12]}"
            )[3]["mode"],
            "apply",
        )
        for body in (
            f"/pullup production-apply {SHA}",
            f"/pullup production-apply {SHA} {'b' * 12} {'c' * 12} PRODUCTION-APPLY-{'d' * 12}",
            f"/pullup production-preflight {SHA}",
            f"/pullup staging-deploy {SHA} {'b' * 12} {'c' * 12}",
            f"/pullup rollback-check {SHA} R3 /root/backups/../secret.manifest",
            f"/pullup rollback-apply {SHA} R3 /root/backups/a.manifest",
        ):
            with self.subTest(body=body), self.assertRaises(t.Refused):
                t.command(body)

    def test_merged_pr_supported_but_unmerged_closed_pr_refused(self):
        a = API()
        a.pr.update(state="closed", merged=True)
        self.assertIn("accepted", a.run())
        a.pr["merged"] = False
        with self.assertRaises(t.Refused):
            t.validate_pr(a.pr, 400, SHA)

    def test_release_gates_require_complete_ci(self):
        evidence = CheckAPI()
        checks = evidence.checks

        def api(method, path, body=None):
            if (path.startswith("commits/") and "/check-runs?" in path) or path.startswith(
                "actions/"
            ):
                return evidence(method, path, body)
            if path.startswith("git/commits/"):
                return {"tree": {"sha": "tree"}}
            if path == "commits/main":
                return {"commit": {"tree": {"sha": "tree"}}}
            raise AssertionError(path)

        t.release_gates(api, "staging-deploy", SHA, {})
        for conclusion in ("failure", "cancelled", "skipped"):
            checks[0]["conclusion"] = conclusion
            with self.subTest(conclusion=conclusion), self.assertRaises(t.Refused):
                t.release_gates(api, "staging-deploy", SHA, {})

    def test_queued_candidate_uses_execution_not_dispatch_time(self):
        deployed = {"id": 5, "created_at": "2026-01-01T10:00:00Z"}
        previous = {"id": 4, "updated_at": "2026-01-01T10:05:00Z"}

        def api(method, path, body=None):
            if path.startswith("actions/runs/5/jobs?"):
                return {"total_count": 1, "jobs": [{"started_at": "2026-01-01T10:06:00Z"}]}
            if "deploy-staging.yml/runs?" in path:
                return {"workflow_runs": [previous]}
            return {"workflow_runs": [deployed]}

        t.unchanged_staging(api, deployed)
        previous["updated_at"] = "2026-01-01T10:07:00Z"
        with self.assertRaises(t.Refused):
            t.unchanged_staging(api, deployed)

    def test_production_requires_ordered_fresh_qa_preflight_and_latest_staging(self):
        stamp = datetime.now(UTC).isoformat()
        evidence = CheckAPI()
        titles = {
            t.WORKFLOW: f"Guarded staging {SHA} dry-run yes",
            "release-qa.yml": f"Release QA {SHA} full-v2",
            "production-deploy.yml": f"Guarded production {SHA} preflight {'b' * 12} {'c' * 12}",
        }
        runs = {
            name: [
                {
                    "id": index,
                    "display_title": title,
                    "head_branch": "main",
                    "event": "workflow_dispatch",
                    "status": "completed",
                    "conclusion": "success",
                    "created_at": stamp,
                    "updated_at": stamp,
                }
            ]
            for index, (name, title) in enumerate(titles.items(), 1)
        }

        runs["deploy-staging.yml"] = []

        def api(method, path, body=None):
            if path.startswith("actions/runs/1/jobs?"):
                return {"total_count": 1, "jobs": [{"started_at": stamp}]}
            if "/check-runs?" in path:
                return evidence(method, path, body)
            if path.startswith("actions/runs/") and not path.startswith("actions/runs/1/"):
                return evidence(method, path, body)
            if path.startswith("actions/workflows/") and "/runs?" not in path:
                return evidence(method, path, body)
            if path.startswith("git/commits/"):
                return {"tree": {"sha": "tree"}}
            if path == "commits/main":
                return {"commit": {"tree": {"sha": "tree"}}}
            if "/runs?" in path:
                return {"workflow_runs": runs[path.split("/")[2]]}
            raise AssertionError(path)

        inputs = {"from_rev": "b" * 12, "to_rev": "c" * 12}
        t.release_gates(api, "production-apply", SHA, inputs)
        for status in ("in_progress", "completed"):
            runs["deploy-staging.yml"] = [
                {
                    "id": 99,
                    "created_at": stamp,
                    "head_branch": "codex/other",
                    "status": status,
                    "conclusion": "failure",
                }
            ]
            with self.assertRaises(t.Refused):
                t.release_gates(api, "production-apply", SHA, inputs)
            with self.assertRaises(t.Refused):
                t.release_gates(api, "staging-qa", SHA, {})
        runs["deploy-staging.yml"] = []
        # A rerun keeps its old created_at, but executes and changes staging now.
        runs["deploy-staging.yml"] = [
            {
                "id": 99,
                "created_at": "2020-01-01T00:00:00Z",
                "updated_at": stamp,
                "run_started_at": stamp,
                "run_attempt": 2,
            }
        ]
        with self.assertRaises(t.Refused):
            t.release_gates(api, "staging-qa", SHA, {})
        runs["deploy-staging.yml"] = []
        # Diagnostic QA can carry the same candidate SHA while running only one project/journey.
        runs["release-qa.yml"][0]["display_title"] = f"Staging QA {SHA}"
        with self.assertRaises(t.Refused):
            t.release_gates(api, "production-apply", SHA, inputs)
        runs["release-qa.yml"][0]["display_title"] = titles["release-qa.yml"]
        runs["release-qa.yml"][0]["conclusion"] = "failure"
        with self.assertRaises(t.Refused):
            t.release_gates(api, "production-apply", SHA, inputs)
        runs["release-qa.yml"][0]["conclusion"] = "success"
        runs["production-deploy.yml"][0]["updated_at"] = "2020-01-01T00:00:00Z"
        with self.assertRaises(t.Refused):
            t.release_gates(api, "production-apply", SHA, inputs)
        runs["production-deploy.yml"][0]["updated_at"] = stamp
        runs[t.WORKFLOW].insert(0, {"display_title": f"Guarded staging {'d' * 40} dry-run yes"})
        with self.assertRaises(t.Refused):
            t.release_gates(api, "production-apply", SHA, inputs)

    def test_payload_and_duplicate(self):
        a = API()
        self.assertIn("accepted", a.run())
        self.assertEqual(
            a.dispatched()[0][2],
            {
                "ref": "main",
                "inputs": {"sha": SHA, "converge": "preflight", "start": "no", "users": "-"},
            },
        )
        self.assertIn("duplicate", a.run())
        self.assertEqual(len(a.dispatched()), 1)

    def test_dispatch_timeout_claim_persists(self):
        a = API()
        a.fail = f"actions/workflows/{t.WORKFLOW}/dispatches"
        with self.assertRaises(TimeoutError):
            a.run()
        self.assertEqual(len(a.comments), 1)
        self.assertIn("duplicate", a.run())
        self.assertEqual(len(a.dispatched()), 1)

    def test_claim_timeout_does_not_dispatch(self):
        a = API()
        a.fail = "issues/400/comments"
        with self.assertRaises(TimeoutError):
            a.run()
        self.assertEqual(a.dispatched(), [])

    def test_head_changes_after_claim(self):
        a = API()
        a.heads = [SHA, SHA, "b" * 40]
        with self.assertRaises(t.Refused):
            a.run()
        self.assertEqual(len(a.comments), 1)
        self.assertEqual(a.dispatched(), [])

    def test_reject_before_side_effects(self):
        mutations = [
            lambda a: a.event.update(action="edited"),
            lambda a: a.runtime.update(repository="evil/repo"),
            lambda a: a.runtime.update(
                workflow_ref=f"{t.REPO}/{t.DISPATCHER}@refs/heads/codex/probe"
            ),
            lambda a: a.event["repository"].update(full_name="evil/repo"),
            lambda a: a.event["repository"].update(id=999),
            lambda a: a.event["comment"]["user"].update(id=2),
            lambda a: a.event["sender"].update(id=2),
            lambda a: a.event["sender"].update(login="evil"),
            lambda a: a.event["comment"].update(author_association="MEMBER"),
            lambda a: a.event["comment"]["user"].update(type="Bot"),
            lambda a: a.event["issue"].pop("pull_request"),
            lambda a: a.event["issue"].update(number=372),
            lambda a: a.event["issue"].update(number=374),
            lambda a: a.pr["head"]["repo"].update(full_name="evil/repo"),
            lambda a: a.pr["base"].update(ref="develop/current"),
            lambda a: a.pr.update(state="closed"),
            lambda a: a.pr["head"].update(ref="main"),
            lambda a: a.pr["head"].update(sha="b" * 40),
        ]
        for cmd in [
            f"/pullup production {SHA}",
            f"/pullup staging-preflight {SHA}\nextra-command",
            f"/pullup staging-preflight {SHA}; extra-command",
            f"/pullup staging-preflight {SHA} ",
            "/pullup staging-preflight main",
        ]:
            mutations.append(lambda a, cmd=cmd: a.event["comment"].update(body=cmd))
        for i, mutate in enumerate(mutations):
            with self.subTest(case=i):
                a = API()
                mutate(a)
                with self.assertRaises(t.Refused):
                    a.run()
                self.assertEqual([c for c in a.calls if c[0] != "GET"], [])

    def test_fake_claim_ignored(self):
        a = API()
        a.comments = [
            {
                "body": f"<!-- pullup-preflight-v1:400:{SHA} -->",
                "user": {"id": 666, "login": "github-actions[bot]"},
            }
        ]
        self.assertIn("accepted", a.run())
        self.assertEqual(len(a.dispatched()), 1)


if __name__ == "__main__":
    unittest.main()
