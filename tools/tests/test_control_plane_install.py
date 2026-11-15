"""Bootstrap stages a complete controller before changing the forced launcher."""

import importlib.util
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.tests.test_control_plane import NEW, ROOT, TREE, blobs, c

SPEC = importlib.util.spec_from_file_location(
    "controller_installer", ROOT / "deploy/install-control-plane.py"
)
i = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(i)
SUPERVISOR = (ROOT / "deploy/control-plane-supervisor.py").read_bytes()
LAUNCHER = (ROOT / "deploy/control-plane-entrypoint.sh").read_bytes()


def fixture(path):
    binary, backups = path / "bin", path / "backups"
    binary.mkdir(mode=0o700)
    backups.mkdir(mode=0o700)
    old = blobs("installed")
    for name, blob in old.items():
        (binary / name).write_bytes(blob)
        (binary / name).chmod(0o700)
    (binary / "authorized_keys").write_bytes(b"unchanged synthetic key")
    (binary / "authorized_keys").chmod(0o600)
    candidate = blobs("reviewed")
    for name in ("deploy-production-guarded-run.sh", "rollback-production-guarded.sh"):
        candidate[name] = old[name]
    return (
        binary,
        backups / "cloud-controller",
        candidate,
        {name: c.digest(blob) for name, blob in old.items()},
    )


def install(binary, ledger, candidate, expected, apply=True):
    return i.install(
        c,
        binary,
        ledger,
        NEW,
        TREE,
        candidate,
        SUPERVISOR,
        LAUNCHER,
        apply=apply,
        expected=expected,
    )


class InstallTests(unittest.TestCase):
    def test_dry_run_idempotence_and_exact_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, ledger, candidate, expected = fixture(Path(directory))
            protected = {
                p.name: (p.stat().st_ino, p.read_bytes())
                for p in binary.iterdir()
                if p.name != "prod-guarded-dispatch.sh"
            }
            self.assertFalse(install(binary, ledger, candidate, expected, apply=False)["installed"])
            self.assertFalse((binary / "control-plane").exists())
            self.assertTrue(install(binary, ledger, candidate, expected)["changed"])
            self.assertFalse(install(binary, ledger, candidate, expected)["changed"])
            for name, identity in protected.items():
                self.assertEqual(
                    ((binary / name).stat().st_ino, (binary / name).read_bytes()), identity
                )
            for name in c.FILES:
                self.assertEqual(
                    c.digest((binary / "control-plane.bootstrap-before" / name).read_bytes()),
                    expected[name],
                )

    def test_real_kill_before_and_after_launcher_then_resume_known_bootstrap(self):
        for point in (
            "bootstrap-backup-published",
            "bootstrap-supervisor-published",
            "bundle-renamed",
            "activation-published",
            "bootstrap-ready",
            "bootstrap-launcher-published",
            "bootstrap-launcher-directory-synced",
        ):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                binary, ledger, candidate, expected = fixture(Path(directory))
                script = """import os, signal, sys
from pathlib import Path
from unittest.mock import patch
from tools.tests.test_control_plane_install import c, install
import json
root=Path(sys.argv[1]); candidate={k:bytes.fromhex(v) for k,v in json.loads(sys.argv[3]).items()}; expected=json.loads(sys.argv[4])
def crash(stage):
    if stage==sys.argv[2]: os.kill(os.getpid(),signal.SIGKILL)
with patch.object(c,"checkpoint",side_effect=crash): install(root/"bin",root/"backups/cloud-controller",candidate,expected)
"""
                import json

                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        script,
                        directory,
                        point,
                        json.dumps({k: v.hex() for k, v in candidate.items()}),
                        json.dumps(expected),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
                self.assertEqual(result.returncode, -signal.SIGKILL, result.stderr.decode())
                launcher_live = (binary / "prod-guarded-dispatch.sh").read_bytes() == LAUNCHER
                if launcher_live:
                    supervisor = c.Supervisor(binary / "control-plane", ledger)
                    supervisor.bundle(supervisor.activation()["active"])
                    self.assertEqual(
                        (binary / "control-plane-supervisor.py").read_bytes(), SUPERVISOR
                    )
                self.assertTrue(install(binary, ledger, candidate, expected)["installed"])

    def test_unknown_installed_file_symlink_or_changed_runner_refuses_before_write(self):
        for case in ("unknown", "symlink", "runner"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                binary, ledger, candidate, expected = fixture(Path(directory))
                if case == "unknown":
                    (binary / "server-control.py").write_bytes(b"unknown")
                elif case == "symlink":
                    (binary / "server-control.py").unlink()
                    (binary / "server-control.py").symlink_to(binary / "authorized_keys")
                else:
                    candidate["deploy-production-guarded-run.sh"] = b"#!/bin/bash\nexit 9\n"
                with self.assertRaises(c.Refused):
                    install(binary, ledger, candidate, expected)
                self.assertFalse((binary / "control-plane").exists())


if __name__ == "__main__":
    unittest.main()
