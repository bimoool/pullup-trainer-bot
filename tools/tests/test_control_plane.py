"""Synthetic Linux processes and files only; SIGKILL bypasses exception cleanup."""

import contextlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "controller_supervisor", ROOT / "deploy/control-plane-supervisor.py"
)
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)
OLD, NEW, TREE = "a" * 40, "b" * 40, "c" * 40


def blobs(label):
    return {
        name: (
            f"# {label}\npass\n" if name.endswith(".py") else f"#!/bin/bash\n# {label}\nexit 0\n"
        ).encode()
        for name in c.FILES
    }


def fixture(path):
    for directory in (path / "control", path / "control/releases", path / "ledger"):
        directory.mkdir(mode=0o700)
    for index in range(3):
        (path / f"lock{index}").write_bytes(b"existing lock")
        (path / f"lock{index}").chmod(0o600)
    supervisor = c.Supervisor(path / "control", path / "ledger")
    reference = supervisor.stage(OLD, TREE, blobs("old"))
    supervisor.activate(
        {
            "version": 1,
            "generation": 1,
            "active": reference,
            "previous": None,
            "operation_id": "bootstrap",
        }
    )
    return supervisor


@contextlib.contextmanager
def isolated(path):
    actual = c.locks
    with (
        patch.object(
            c, "locks", side_effect=lambda: actual(tuple(path / f"lock{i}" for i in range(3)))
        ),
        patch.object(c, "not_busy"),
        patch.object(c, "source", return_value=(TREE, blobs("new"))),
    ):
        yield


def child():
    path, event, action, operation = Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
    supervisor = c.Supervisor(path / "control", path / "ledger")

    def crash(stage):
        if stage == event:
            os.kill(os.getpid(), signal.SIGKILL)

    with isolated(path), patch.object(c, "checkpoint", side_effect=crash):
        if action == "claim":
            supervisor.store.claim({"operation_id": operation, "candidate": NEW, "action": "adopt"})
        else:
            supervisor.operate(action, NEW, operation, "ops-1" if action == "recover" else None)


class ControllerTests(unittest.TestCase):
    def kill(self, path, point, action="adopt", operation="ops-1"):
        result = subprocess.run(
            [sys.executable, __file__, "_crash", str(path), point, action, operation],
            capture_output=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, -signal.SIGKILL, result.stderr.decode())

    def test_complete_claim_publication_survives_kill_and_deduplicates(self):
        for point in ("claim-file-synced", "claim-published", "claim-directory-synced"):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                supervisor = fixture(path)
                self.kill(path, point, "claim")
                record = supervisor.store.get("ops-1")
                if point == "claim-file-synced":
                    self.assertIsNone(record)
                else:
                    self.assertEqual(record["candidate"], NEW)
                    self.assertFalse(supervisor.store.claim(record))

    def test_adoption_crash_matrix_recovers_without_replaying_adoption(self):
        points = (
            "claim-published",
            "claim-directory-synced",
            "claimed",
            "receipt-published",
            "bundle-file-published",
            "manifest-published",
            "bundle-before-rename",
            "bundle-renamed",
            "bundle-directory-synced",
            "activation-file-synced",
            "activation-published",
            "activation-directory-synced",
            "before-final-receipt",
        )
        for point in points:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                supervisor = fixture(path)
                self.kill(path, point)
                self.assertIn(supervisor.activation()["active"]["sha"], {OLD, NEW})
                with (
                    isolated(path),
                    patch.object(c, "source", side_effect=AssertionError("must not refetch")),
                ):
                    recovered = supervisor.operate("recover", NEW, "ops-2", "ops-1")
                    self.assertEqual(recovered["state"], "VERIFIED", recovered)
                    self.assertEqual(supervisor.activation()["active"]["sha"], OLD)
                    supervisor.operate("adopt", NEW, "ops-1")
                    self.assertEqual(
                        supervisor.operate("recover", NEW, "ops-2", "ops-1"), recovered
                    )

    def test_recovery_kill_is_reconciled_without_second_pointer_switch(self):
        for point in (
            "activation-file-synced",
            "activation-published",
            "activation-directory-synced",
            "before-final-receipt",
        ):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                supervisor = fixture(path)
                with isolated(path):
                    self.assertEqual(supervisor.operate("adopt", NEW, "ops-1")["state"], "VERIFIED")
                self.kill(path, point, "recover", "ops-2")
                generation = supervisor.activation()["generation"]
                with isolated(path):
                    result = supervisor.operate("recover", NEW, "ops-3", "ops-1")
                self.assertEqual(result["state"], "VERIFIED", result)
                self.assertEqual(supervisor.activation()["active"]["sha"], OLD)
                self.assertEqual(supervisor.activation()["generation"], 3)
                if point != "activation-file-synced":
                    self.assertEqual(generation, 3)

    def test_broken_active_bundle_cannot_disable_status_or_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            supervisor = fixture(path)
            with isolated(path):
                self.assertEqual(supervisor.operate("adopt", NEW, "ops-1")["state"], "VERIFIED")
                (supervisor.releases / NEW / "prod-guarded-dispatch.sh").write_bytes(
                    b"broken syntax ("
                )
                self.assertEqual(supervisor.status(NEW, "ops-1")["active_sha"], NEW)
                with self.assertRaises(c.Refused):
                    supervisor.bundle(supervisor.activation()["active"])
                self.assertEqual(
                    supervisor.operate("recover", NEW, "ops-2", "ops-1")["state"], "VERIFIED"
                )
                self.assertEqual(supervisor.activation()["active"]["sha"], OLD)

    def test_later_activation_and_unknown_state_refuse_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            supervisor = fixture(path)
            with isolated(path):
                supervisor.operate("adopt", NEW, "ops-1")
                current = supervisor.activation()
                current["generation"] += 1
                supervisor.activate(current)
                self.assertEqual(
                    supervisor.operate("recover", NEW, "ops-2", "ops-1")["state"], "FAILED"
                )
                self.assertEqual(supervisor.activation(), current)

    def test_dedup_binding_and_busy_existing_lock_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            supervisor = fixture(path)
            before = [(path / f"lock{i}").stat().st_ino for i in range(3)]
            with c.locks((path / "lock0",)), isolated(path):
                result = supervisor.operate("adopt", NEW, "ops-1")
                self.assertEqual(result["state"], "BLOCKED")
                self.assertEqual(result["error"], "BUSY")
            with isolated(path), patch.object(c, "source", side_effect=AssertionError("replay")):
                self.assertEqual(supervisor.operate("adopt", NEW, "ops-1"), result)
                with self.assertRaises(c.Refused):
                    supervisor.operate("adopt", OLD, "ops-1")
            self.assertEqual(before, [(path / f"lock{i}").stat().st_ino for i in range(3)])

    def test_symlinks_unknown_members_permissions_and_syntax_refuse(self):
        for case in ("symlink", "extra", "permissions", "syntax"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                supervisor = fixture(path)
                if case == "syntax":
                    bad = blobs("new")
                    bad["server-control.py"] = b"def broken(:"
                    with isolated(path), patch.object(c, "source", return_value=(TREE, bad)):
                        result = supervisor.operate("adopt", NEW, "ops-1")
                        self.assertEqual(result["state"], "FAILED")
                else:
                    target = supervisor.releases / OLD / "server-control.py"
                    if case == "symlink":
                        target.unlink()
                        target.symlink_to(supervisor.releases / OLD / "prod-guarded-dispatch.sh")
                    elif case == "extra":
                        (supervisor.releases / OLD / "extra").write_bytes(b"no")
                    else:
                        target.chmod(0o755)
                    with self.assertRaises(c.Refused):
                        supervisor.bundle(supervisor.activation()["active"])
                self.assertEqual(supervisor.activation()["active"]["sha"], OLD)

    def test_only_bounded_fixed_command_envelopes_delegate(self):
        self.assertTrue(c.allowed_delegate(f"prod-control future-reviewed-action {NEW} ops-123"))
        self.assertTrue(
            c.allowed_delegate(f"prod-guarded {NEW} preflight aaaaaaaaaaaa bbbbbbbbbbbb")
        )
        for command in (
            "bash",
            f"prod-control x {NEW} ops-1;id",
            f"prod-control /tmp/x {NEW} ops-1",
            f"prod-control x {NEW} ops-1\n",
            "prod-rollback R1 /root/backups/../x.manifest check",
        ):
            self.assertFalse(c.allowed_delegate(command))

    def test_directory_fsync_follows_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            calls = []
            with (
                patch.object(c, "checkpoint", side_effect=calls.append),
                patch.object(
                    c, "sync_directory", side_effect=lambda p: calls.append("fsync-directory")
                ),
            ):
                c.atomic(root / "claim.json", b"{}", exclusive=True, event="claim")
            self.assertEqual(
                calls,
                [
                    "claim-file-synced",
                    "claim-published",
                    "fsync-directory",
                    "claim-directory-synced",
                ],
            )

    def test_actual_exec_handoff_uses_one_complete_bundle_and_inherited_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            supervisor = fixture(path)
            candidate = blobs("new")
            candidate["prod-guarded-dispatch.sh"] = (
                (ROOT / "deploy/prod-guarded-dispatch.sh")
                .read_text()
                .replace("LOCK_DIR=/root/backups", "LOCK_DIR=" + str(path))
                .encode()
            )
            (path / ".prod-actions.lock").write_bytes(b"existing")
            (path / ".prod-actions.lock").chmod(0o600)
            candidate["server-control.py"] = (
                b'import os,json\nprint(json.dumps({"helper":__file__,"inode":os.fstat(9).st_ino}))\n'
            )
            with isolated(path), patch.object(c, "source", return_value=(TREE, candidate)):
                self.assertEqual(supervisor.operate("adopt", NEW, "ops-1")["state"], "VERIFIED")
            script = """from pathlib import Path
import sys
from tools.tests.test_control_plane import c, NEW
p=Path(sys.argv[1]); c.LOCKS=(p/".prod-actions.lock", p/"lock1", p/"lock2")
c.delegate(c.Supervisor(p/"control",p/"ledger"),"prod-control readiness "+NEW+" ops-9")
"""
            result = subprocess.run(
                [sys.executable, "-c", script, directory],
                cwd=ROOT,
                capture_output=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            observation = json.loads(result.stdout)
            self.assertEqual(
                observation["helper"], str(supervisor.releases / NEW / "server-control.py")
            )
            self.assertEqual(observation["inode"], (path / ".prod-actions.lock").stat().st_ino)

    def test_fixed_origin_main_tree_and_regular_git_mode_are_independent_server_gates(self):
        for case in ("origin", "tree", "symlink"):
            calls = []

            def source_command(args, case=case, calls=calls, **kwargs):
                calls.append(args)
                if "get-url" in args:
                    return (
                        b"https://attacker.invalid/repo"
                        if case == "origin"
                        else b"https://github.com/bimoool/pullup-trainer-bot.git"
                    )
                if "rev-parse" in args:
                    return (
                        "d" * 40 if case == "tree" and args[-1].startswith("refs/") else TREE
                    ).encode()
                if "ls-tree" in args:
                    return ("120000 blob " + OLD + "\t" + args[-1] + "\n").encode()
                return b""

            with (
                self.subTest(case=case),
                patch.object(c, "run", side_effect=source_command),
                self.assertRaises(c.Refused),
            ):
                c.source(NEW)
            self.assertFalse(any("show" in args for args in calls))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "_crash":
        child()
    else:
        unittest.main()
