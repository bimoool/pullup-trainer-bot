"""Offline authorization and at-most-once failure-path checks."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guarded_comment_dispatch as t

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
                return {"path": f".github/workflows/{t.WORKFLOW}", "state": "active"}
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
