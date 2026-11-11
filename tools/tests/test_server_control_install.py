import hashlib
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "control_installer", ROOT / "deploy/install-server-control.py"
)
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


class InstallTests(unittest.TestCase):
    def test_checked_install_preserves_old_policy_keys_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            old = b"#!/bin/bash\nexit 23\n"
            (p / "prod-guarded-dispatch.sh").write_bytes(old)
            (p / "authorized_keys").write_bytes(b"existing synthetic key")
            blobs = {
                "server-control.py": b'print("trusted helper")\n',
                "prod-guarded-dispatch.sh": b"#!/bin/bash\nexit 24\n",
            }
            baseline = hashlib.sha256(old).hexdigest()
            self.assertFalse(t.install(p, blobs, baseline_hash=baseline)["installed"])
            self.assertEqual((p / "prod-guarded-dispatch.sh").read_bytes(), old)
            self.assertTrue(t.install(p, blobs, baseline_hash=baseline, apply=True)["changed"])
            self.assertFalse(t.install(p, blobs, baseline_hash=baseline, apply=True)["changed"])
            self.assertEqual(
                (p / "prod-guarded-dispatch.before-cloud-control.sh").read_bytes(), old
            )
            self.assertEqual((p / "authorized_keys").read_bytes(), b"existing synthetic key")

    def test_unknown_policy_and_helper_refused(self):
        for target in ["prod-guarded-dispatch.sh", "server-control.py"]:
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp)
                old = b"old"
                (p / "prod-guarded-dispatch.sh").write_bytes(old)
                if target == "server-control.py":
                    (p / target).write_bytes(b"unknown")
                blobs = {"server-control.py": b"pass\n", "prod-guarded-dispatch.sh": b"new"}
                baseline = hashlib.sha256(
                    old if target != "prod-guarded-dispatch.sh" else b"other"
                ).hexdigest()
                with self.assertRaises(RuntimeError):
                    t.install(p, blobs, baseline_hash=baseline, apply=True)
                self.assertEqual((p / "prod-guarded-dispatch.sh").read_bytes(), old)
                self.assertFalse((p / "prod-guarded-dispatch.before-cloud-control.sh").exists())

    def test_shared_staging_lock_preserved_but_foreign_owner_and_root_group_write_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "staging.lock"
            lock.write_text("synthetic shared lock")
            lock.chmod(0o664)
            before = lock.stat()
            identity = Mock(pw_uid=os.geteuid(), pw_gid=os.getegid())
            with patch.object(t.pwd, "getpwnam", return_value=identity):
                fd = t.acquire_install_lock(lock, staging=True)
                os.close(fd)
            after = lock.stat()
            self.assertEqual((before.st_ino, before.st_mode), (after.st_ino, after.st_mode))
            self.assertEqual(lock.read_text(), "synthetic shared lock")
            with self.assertRaises(RuntimeError):
                t.acquire_install_lock(lock, staging=False)
            identity.pw_uid += 1
            with (
                patch.object(t.pwd, "getpwnam", return_value=identity),
                self.assertRaises(RuntimeError),
            ):
                t.acquire_install_lock(lock, staging=True)
            alias = Path(tmp) / "symlink"
            alias.symlink_to(lock)
            with self.assertRaises(RuntimeError):
                t.acquire_install_lock(alias, staging=False)
