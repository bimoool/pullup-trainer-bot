"""Synthetic files only: runner adoption and exact R1 recovery command regression."""

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guarded_comment_dispatch as dispatcher

spec = importlib.util.spec_from_file_location(
    "adoption_control", Path(__file__).resolve().parents[2] / "deploy/server-control.py"
)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
SHA = "a" * 40
MANIFEST = "/root/backups/prod-pre-aaaaaaa-20261115T120000Z.manifest"
TOKEN = "ROLLBACK-R1-prod-aaaaaaa-20261115T120000Z-123"


class ContinuityTests(unittest.TestCase):
    def test_fixed_cloud_commands_route(self):
        self.assertEqual(
            dispatcher.command(f"/pullup server-adopt-runner {SHA}")[3]["operation"], "adopt-runner"
        )
        op, sha, workflow, inputs = dispatcher.command(
            f"/pullup rollback-r1-apply {SHA} {MANIFEST} {TOKEN} 1234 1235"
        )
        self.assertEqual((op, sha, workflow), ("rollback-r1-apply", SHA, "production-rollback.yml"))
        self.assertEqual(inputs["kind"], "R1")
        self.assertEqual(inputs["mode"], "apply")
        for bad in [
            TOKEN.replace("R1", "R3"),
            TOKEN.replace("aaaaaaa", "bbbbbbb"),
            TOKEN.replace("120000Z", "120001Z"),
            TOKEN + ";id",
        ]:
            with self.assertRaises(dispatcher.Refused):
                dispatcher.command(f"/pullup rollback-r1-apply {SHA} {MANIFEST} {bad} 1234 1235")

    def fixture(self, root):
        binary = root / "bin"
        binary.mkdir(mode=0o700)
        ledger = root / "ledger"
        ledger.mkdir(mode=0o700)
        keys = root / "authorized_keys"
        keys.write_bytes(b"fixed original key\n")
        keys.chmod(0o600)
        old = b"#!/bin/bash\nprintf old\\n\n"
        new = b"#!/bin/bash\nprintf new\\n\n"
        for name in [
            "deploy-production-guarded-run.sh",
            "rollback-production-guarded.sh",
            "prod-guarded-dispatch.sh",
            "server-control.py",
        ]:
            (binary / name).write_bytes(old)
            (binary / name).chmod(0o700)
        return binary, ledger, keys, old, new

    def candidate_command(self, blob):
        def command(args, **kwargs):
            if args[0] == "bash":
                return control.subprocess.check_output(args)
            if "get-url" in args:
                return b"https://github.com/bimoool/pullup-trainer-bot.git"
            if "rev-parse" in args:
                return b"b" * 40
            return blob

        return command

    def test_adoption_changes_only_fixed_runner_preserves_backup_and_durable_state(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, ledger, keys, old, new = self.fixture(Path(directory))
            before = {
                p: p.read_bytes()
                for p in [
                    keys,
                    binary / "rollback-production-guarded.sh",
                    binary / "prod-guarded-dispatch.sh",
                    binary / "server-control.py",
                ]
            }
            with (
                patch.object(control, "BIN", binary),
                patch.object(control, "LEDGER", ledger),
                patch.object(control, "AUTHORIZED_KEYS", keys),
                patch.object(control, "INITIAL_RUNNER_HASH", hashlib.sha256(old).hexdigest()),
                patch.object(control, "command", side_effect=self.candidate_command(new)),
            ):
                result = control.adopt_runner(SHA, "ops-1")
                self.assertTrue(result["runner_adopted"])
                self.assertEqual((binary / "deploy-production-guarded-run.sh").read_bytes(), new)
                self.assertEqual((ledger / "ops-1.runner-before").read_bytes(), old)
                self.assertEqual(
                    (binary / "deploy-production-guarded-run.sh").stat().st_mode & 0o777, 0o700
                )
                self.assertTrue(control.adopt_runner(SHA, "ops-2")["runner_adopted"])
                for path, blob in before.items():
                    self.assertEqual(path.read_bytes(), blob)

    def test_unknown_hash_symlinks_permissions_and_pending_state_refuse_without_runner_write(self):
        for case in ["hash", "symlink", "permissions", "pending"]:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                binary, ledger, keys, old, new = self.fixture(Path(directory))
                runner = binary / "deploy-production-guarded-run.sh"
                if case == "symlink":
                    runner.unlink()
                    runner.symlink_to(binary / "rollback-production-guarded.sh")
                if case == "permissions":
                    runner.chmod(0o755)
                if case == "pending":
                    (ledger / "runner-adopted.json").write_text('{"state":"RUNNING"}')
                    (ledger / "runner-adopted.json").chmod(0o600)
                with (
                    patch.object(control, "BIN", binary),
                    patch.object(control, "LEDGER", ledger),
                    patch.object(control, "AUTHORIZED_KEYS", keys),
                    patch.object(
                        control,
                        "INITIAL_RUNNER_HASH",
                        "f" * 64 if case == "hash" else hashlib.sha256(old).hexdigest(),
                    ),
                    patch.object(control, "command", side_effect=self.candidate_command(new)),
                    self.assertRaises(control.Refused),
                ):
                    control.adopt_runner(SHA, "ops-1")
                self.assertEqual(runner.read_bytes(), old)
                self.assertFalse((ledger / "ops-1.runner-before").exists())


if __name__ == "__main__":
    unittest.main()


class AdoptionFailureTests(unittest.TestCase):
    fixture = ContinuityTests.fixture
    candidate_command = ContinuityTests.candidate_command

    def test_wrong_main_tree_refuses_before_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, ledger, keys, old, new = self.fixture(Path(directory))
            source = self.candidate_command(new)

            def command(args, **kwargs):
                if args[-1] == "refs/remotes/origin/main^{tree}":
                    return b"c" * 40
                return source(args, **kwargs)

            with (
                patch.object(control, "BIN", binary),
                patch.object(control, "LEDGER", ledger),
                patch.object(control, "AUTHORIZED_KEYS", keys),
                patch.object(control, "INITIAL_RUNNER_HASH", hashlib.sha256(old).hexdigest()),
                patch.object(control, "command", side_effect=command),
                self.assertRaisesRegex(control.Refused, "TRUSTED_MAIN_TREE"),
            ):
                control.adopt_runner(SHA, "ops-1")
            self.assertEqual((binary / "deploy-production-guarded-run.sh").read_bytes(), old)
            self.assertFalse((ledger / "ops-1.runner-before").exists())

    def test_interrupted_install_retains_pending_state_and_old_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, ledger, keys, old, new = self.fixture(Path(directory))
            atomic = control.atomic_private

            def interrupted(path, blob, mode=0o600):
                atomic(path, blob, mode)
                if path.name == "deploy-production-guarded-run.sh":
                    raise OSError("synthetic loss after rename")

            with (
                patch.object(control, "BIN", binary),
                patch.object(control, "LEDGER", ledger),
                patch.object(control, "AUTHORIZED_KEYS", keys),
                patch.object(control, "INITIAL_RUNNER_HASH", hashlib.sha256(old).hexdigest()),
                patch.object(control, "command", side_effect=self.candidate_command(new)),
                patch.object(control, "atomic_private", side_effect=interrupted),
            ):
                with self.assertRaises(OSError):
                    control.adopt_runner(SHA, "ops-1")
                with self.assertRaisesRegex(control.Refused, "ADOPTION_UNCERTAIN"):
                    control.adopt_runner(SHA, "ops-2")
            self.assertEqual((ledger / "ops-1.runner-before").read_bytes(), old)
            self.assertIn('"RUNNING"', (ledger / "runner-adopted.json").read_text())
            self.assertFalse((ledger / "ops-2.runner-before").exists())

    def test_busy_lock_claims_once_without_source_commands_or_runner_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary, ledger, _keys, old, _ = self.fixture(root)
            with (
                patch.object(control, "BIN", binary),
                patch.object(control, "LEDGER", ledger),
                patch.object(control, "BACKUPS", root),
                patch.object(control, "trusted_directory"),
                patch.object(control.os, "geteuid", return_value=0),
                patch.object(control, "regular", side_effect=lambda path: path.lstat()),
                patch.object(
                    control, "acquire_existing", side_effect=control.Refused("BUSY")
                ) as lock,
                patch.object(control, "command") as command,
            ):
                receipt = control.execute("adopt-runner", SHA, "ops-1")
                self.assertEqual(receipt["state"], "BLOCKED")
                self.assertEqual(receipt["error"], "BUSY")
                self.assertEqual(control.execute("adopt-runner", SHA, "ops-1"), receipt)
                self.assertEqual(lock.call_count, 1)
                command.assert_not_called()
            self.assertEqual((binary / "deploy-production-guarded-run.sh").read_bytes(), old)
