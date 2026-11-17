"""Read-only readiness evidence from synthetic Git and actual filesystem fixtures."""

import errno
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.tests.test_server_control import t
from tools.tests.test_server_control_client import c


class StagingAttestationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root_uid = os.getuid()
        self.deploy_uid = self.root_uid or 65534
        self.home = self.root / "home"
        self.deploy = self.home / "deploy"
        self.deploy.mkdir(parents=True)
        self.set_deploy_owner(self.deploy)
        self.runner = self.deploy / "deploy-staging-guarded-run.sh"
        self.blob = b"#!/bin/sh\n# synthetic runner, never executed\nexit 0\n"
        self.runner.write_bytes(self.blob)
        self.runner.chmod(0o755)
        self.set_deploy_owner(self.runner)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "--quiet")
        self.git("config", "user.name", "Synthetic test")
        self.git("config", "user.email", "synthetic@example.invalid")
        (self.repo / "deploy").mkdir()
        (self.repo / "deploy" / self.runner.name).write_bytes(self.blob)
        self.binary = self.root / "bin"
        self.binary.mkdir()
        for name in t.RUNNERS:
            (self.binary / name).write_bytes(b"# synthetic root runner\n")
            (self.repo / "deploy" / name).write_bytes(b"# synthetic root runner\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Synthetic candidate")
        self.sha = self.git("rev-parse", "HEAD").decode().strip()

    def set_deploy_owner(self, path):
        # Root fixtures must still model a separate, nonroot deploy account.
        # Change ownership only within this test's temporary staging directory.
        self.assertTrue(path == self.deploy or path.parent == self.deploy)
        if self.root_uid == 0:
            os.chown(path, self.deploy_uid, -1, follow_symlinks=False)

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], capture_output=True, check=True
        ).stdout

    @contextmanager
    def observation_environment(self):
        # Redirect only the fixed root descriptor into a synthetic tree. All
        # subsequent open/fstat/stat/read calls still hit the real filesystem.
        original_open = os.open

        def open_fixed(path, flags, *args, **kwargs):
            if path == "/":
                path = self.root
            return original_open(path, flags, *args, **kwargs)

        with (
            patch.object(t, "REPO", self.repo),
            patch.object(t, "BIN", self.binary),
            patch.object(t, "resources", return_value=(1000, 10000)),
            patch.object(
                t, "service", return_value=("synthetic", {"Image": "sha256:abc", "State": {}})
            ),
            patch.object(t, "query", return_value="b5d8e1f3a6c9"),
            patch.object(t.os, "open", side_effect=open_fixed),
            patch.object(t, "STAGING_ROOT_UID", self.root_uid, create=True),
            patch(
                "pwd.getpwnam",
                return_value=SimpleNamespace(pw_uid=self.deploy_uid, pw_dir="/home/deploy"),
            ),
        ):
            yield

    def observe(self, sha=None):
        with self.observation_environment():
            return t.observation(sha or self.sha)

    def test_readiness_attests_fixed_staging_bytes_separately_from_root_runners(self):
        facts = self.observe()
        expected = hashlib.sha256(self.blob).hexdigest()
        self.assertEqual(set(facts["runner_hashes"]), set(t.RUNNERS))
        self.assertTrue(all(item["match"] for item in facts["runner_hashes"].values()))
        self.assertEqual(
            facts["staging_runner_attestation"],
            {
                "installed_state": "PRESENT",
                "installed": expected,
                "candidate_state": "PRESENT",
                "candidate": expected,
                "match": True,
            },
        )

    def attestation(self, sha=None):
        return self.observe(sha)["staging_runner_attestation"]

    def assert_unknown_match(self, state):
        facts = self.attestation()
        self.assertEqual(facts["installed_state"], state)
        self.assertIsNone(facts["installed"])
        self.assertIsNone(facts["match"])
        self.assertEqual(facts["candidate_state"], "PRESENT")

    def test_byte_mismatch_is_explicit_and_does_not_change_root_matches(self):
        self.runner.write_bytes(b"# different synthetic runner\n")
        facts = self.observe()
        self.assertFalse(facts["staging_runner_attestation"]["match"])
        self.assertTrue(all(item["match"] for item in facts["runner_hashes"].values()))

    def test_absent_installed_file_keeps_observation_available(self):
        self.runner.unlink()
        self.assert_unknown_match("ABSENT")

    def test_symlink_file_is_not_followed_or_exported(self):
        secret = self.root / "private-synthetic"
        secret.write_bytes(b"synthetic-private-marker")
        self.runner.unlink()
        self.runner.symlink_to(secret)
        self.assert_unknown_match("UNTRUSTED")
        self.assertNotIn("synthetic-private-marker", json.dumps(self.observe()))

    def test_symlink_directory_is_not_followed(self):
        original = self.home / "elsewhere"
        self.deploy.rename(original)
        self.deploy.symlink_to(original, target_is_directory=True)
        self.assert_unknown_match("UNTRUSTED")

    def test_untrusted_file_modes_and_size_are_never_hashed(self):
        for mode in [0o777, 0o775, 0o4755, 0o644, 0o700]:
            with self.subTest(mode=oct(mode)):
                self.runner.chmod(mode)
                self.assert_unknown_match("UNTRUSTED")
        self.runner.chmod(0o755)
        for blob in [b"", b"x" * 262145]:
            with self.subTest(size=len(blob)):
                self.runner.write_bytes(blob)
                self.assert_unknown_match("UNTRUSTED")

    def test_directory_mode_and_file_type_and_hardlinks_are_untrusted(self):
        self.deploy.chmod(0o777)
        self.assert_unknown_match("UNTRUSTED")
        self.deploy.chmod(0o755)
        os.link(self.runner, self.root / "alias")
        self.assert_unknown_match("UNTRUSTED")
        self.runner.unlink()
        os.mkfifo(self.runner)
        self.set_deploy_owner(self.runner)
        self.assert_unknown_match("UNTRUSTED")  # Must not block on the FIFO.

    def test_fixed_deploy_identity_must_be_known_nonroot_and_have_expected_home(self):
        for owner in [
            SimpleNamespace(pw_uid=0, pw_dir="/home/deploy"),
            SimpleNamespace(pw_uid=self.deploy_uid, pw_dir="/tmp/untrusted"),
            SimpleNamespace(pw_uid=self.deploy_uid + 1, pw_dir="/home/deploy"),
        ]:
            with (
                patch("pwd.getpwnam", return_value=owner),
                patch.object(t, "STAGING_ROOT_UID", self.root_uid),
            ):
                # This direct fixture uses the same real descriptors while
                # changing only the expected identity, not filesystem metadata.
                original_open = os.open

                def fixed_open(path, flags, *args, original_open=original_open, **kwargs):
                    return original_open(self.root if path == "/" else path, flags, *args, **kwargs)

                with patch.object(t.os, "open", side_effect=fixed_open):
                    self.assertEqual(t.staging_installed_hash(), ("UNTRUSTED", None))
        with patch("pwd.getpwnam", side_effect=KeyError("private marker")):
            self.assertEqual(t.staging_installed_hash(), ("UNKNOWN", None))

    def test_read_failures_are_fixed_unknown_without_exception_text(self):
        original_read = os.read
        expected = self.runner.stat()

        def failing_read(fd, count):
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino):
                raise OSError(errno.EACCES, "private marker")
            return original_read(fd, count)

        with patch.object(t.os, "read", side_effect=failing_read):
            self.assert_unknown_match("UNKNOWN")

    def test_inplace_writes_replacement_and_ancestor_swap_discard_digest(self):
        original_read = os.read
        for case in ["inplace", "replace", "unlink", "ancestor"]:
            with self.subTest(case=case):
                changed = False
                expected = self.runner.stat()

                def read_and_change(fd, count, expected=expected, case=case):
                    nonlocal changed
                    result = original_read(fd, count)
                    info = os.fstat(fd)
                    if not changed and (info.st_dev, info.st_ino) == (
                        expected.st_dev,
                        expected.st_ino,
                    ):
                        changed = True
                        if case == "inplace":
                            self.runner.write_bytes(b"# concurrent synthetic modification\n")
                        elif case == "replace":
                            replacement = self.deploy / "replacement"
                            replacement.write_bytes(self.blob)
                            replacement.chmod(0o755)
                            self.set_deploy_owner(replacement)
                            replacement.replace(self.runner)
                        elif case == "unlink":
                            self.runner.unlink()
                        else:
                            self.deploy.rename(self.home / "old-deploy")
                            self.deploy.mkdir()
                            self.set_deploy_owner(self.deploy)
                            self.runner.write_bytes(self.blob)
                            self.runner.chmod(0o755)
                            self.set_deploy_owner(self.runner)
                    return result

                with patch.object(t.os, "read", side_effect=read_and_change):
                    self.assert_unknown_match("UNKNOWN")
                self.runner.write_bytes(self.blob)
                self.runner.chmod(0o755)
                self.set_deploy_owner(self.runner)

    def test_concurrent_growth_is_bounded_and_hash_is_discarded(self):
        original_read = os.read
        total = 0
        changed = False
        expected = self.runner.stat()

        def growing_read(fd, count):
            nonlocal changed, total
            result = original_read(fd, count)
            info = os.fstat(fd)
            runner = (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino)
            if runner:
                total += len(result)
            if not changed and runner:
                changed = True
                with self.runner.open("ab") as target:
                    target.write(b"x" * 524288)
            return result

        with patch.object(t.os, "read", side_effect=growing_read):
            self.assert_unknown_match("UNKNOWN")
        self.assertLessEqual(total, 262145)

    def test_missing_commit_and_missing_candidate_blob_remain_unknown_match(self):
        for missing_commit in [True, False]:
            with self.subTest(missing_commit=missing_commit):
                if missing_commit:
                    candidate = "f" * 40
                else:
                    self.git("rm", "--quiet", "deploy/" + self.runner.name)
                    self.git("commit", "--quiet", "-m", "Candidate lacks staging runner")
                    candidate = self.git("rev-parse", "HEAD").decode().strip()
                facts = self.attestation(candidate)
                self.assertEqual(facts["candidate_state"], "ABSENT")
                self.assertIsNone(facts["candidate"])
                self.assertIsNone(facts["match"])

    def test_candidate_size_checked_before_blob_materialization(self):
        (self.repo / "deploy" / self.runner.name).write_bytes(b"x" * 262145)
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Oversized synthetic source")
        sha = self.git("rev-parse", "HEAD").decode().strip()
        original_run = subprocess.run
        with patch.object(t.subprocess, "run", wraps=original_run) as run:
            facts = self.attestation(sha)
        self.assertEqual(facts["candidate_state"], "UNTRUSTED")
        self.assertIsNone(facts["candidate"])
        self.assertIsNone(facts["match"])
        self.assertFalse(any("blob" in call.args[0] for call in run.call_args_list))

    def test_candidate_uses_exact_commit_and_never_working_tree_bytes(self):
        (self.repo / "deploy" / self.runner.name).write_bytes(b"# uncommitted synthetic bytes\n")
        self.assertTrue(self.attestation()["match"])

    def test_candidate_git_failure_exports_no_error_text_or_false_match(self):
        original_run = subprocess.run

        def failing_git(args, **kwargs):
            if "--batch-check" in args:
                return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"private marker")
            return original_run(args, **kwargs)

        with patch.object(t.subprocess, "run", side_effect=failing_git):
            facts = self.attestation()
        self.assertEqual(facts["candidate_state"], "UNKNOWN")
        self.assertIsNone(facts["candidate"])
        self.assertIsNone(facts["match"])
        self.assertNotIn("private marker", json.dumps(facts))

    def test_verified_readiness_receipt_does_not_assert_absent_staging_is_verified(self):
        self.runner.unlink()
        backups = self.root / "backups"
        ledger = backups / "cloud-operations"
        ledger.mkdir(parents=True)
        with (
            self.observation_environment(),
            patch.object(t, "BACKUPS", backups),
            patch.object(t, "LEDGER", ledger),
            patch.object(t.os, "geteuid", return_value=0),
            patch.object(t, "trusted_directory"),
            patch.object(t, "regular"),
            patch.object(
                t, "acquire_existing", side_effect=lambda _: os.open(self.root, os.O_RDONLY)
            ),
            patch.object(t, "no_other_operations"),
        ):
            result = t.execute("readiness", self.sha, "ops-10")
        self.assertEqual(result["state"], "VERIFIED")
        facts = result["facts"]["staging_runner_attestation"]
        self.assertEqual(facts["installed_state"], "ABSENT")
        self.assertIsNone(facts["match"])

    def test_observation_never_writes_changes_permissions_or_executes_candidate(self):
        paths = [self.runner, *(self.binary / name for name in t.RUNNERS)]
        before = [
            (p.read_bytes(), p.stat().st_mode, p.stat().st_ino, p.stat().st_mtime_ns) for p in paths
        ]
        head = self.git("rev-parse", "HEAD")
        original_run = subprocess.run
        with patch.object(t.subprocess, "run", wraps=original_run) as run:
            self.observe()
        for call in run.call_args_list:
            self.assertEqual(call.args[0][0], "git")
            self.assertNotIn(call.args[0][3], {"fetch", "checkout", "reset", "update-ref"})
        self.assertEqual(
            before,
            [
                (p.read_bytes(), p.stat().st_mode, p.stat().st_ino, p.stat().st_mtime_ns)
                for p in paths
            ],
        )
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("status", "--porcelain"), b"")

    def test_client_accepts_actual_attestation_and_rejects_malformed_or_leaky_facts(self):
        facts = self.observe()
        receipt = {
            "operation_id": "ops-10",
            "candidate": self.sha,
            "action": "readiness",
            "state": "VERIFIED",
            "facts": facts,
        }
        self.assertEqual(c.safe_receipt(json.dumps(receipt).encode(), self.sha, "ops-10"), receipt)
        attestation = facts["staging_runner_attestation"]
        for change in [
            {"path": "/private/synthetic"},
            {"installed_state": "VERIFIED"},
            {"installed_state": ["PRESENT"]},
            {"installed": "private marker"},
            {"candidate": "f" * 63},
            {"match": 1},
            {"match": False},
            {"installed_state": "UNKNOWN"},
            {"installed_state": "UNKNOWN", "installed": None, "match": False},
        ]:
            with self.subTest(change=change):
                facts["staging_runner_attestation"] = dict(attestation, **change)
                with self.assertRaises(c.Refused):
                    c.safe_receipt(json.dumps(receipt).encode(), self.sha, "ops-10")
        for state in ["ABSENT", "UNTRUSTED", "UNKNOWN"]:
            facts["staging_runner_attestation"] = dict(
                attestation, installed_state=state, installed=None, match=None
            )
            self.assertEqual(
                c.safe_receipt(json.dumps(receipt).encode(), self.sha, "ops-10"), receipt
            )


if __name__ == "__main__":
    unittest.main()
