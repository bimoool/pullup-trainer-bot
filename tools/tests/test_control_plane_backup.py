"""Optional fixed backup code follows controller adoption and local scheduling."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.tests.test_control_plane import NEW, OLD, ROOT, TREE, blobs, c, fixture, isolated


def launcher():
    spec = importlib.util.spec_from_file_location(
        "scheduled_backup", ROOT / "deploy/control-plane-backup.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def backup_blobs(label="new"):
    result = blobs(label)
    result["drive-backup.py"] = (
        b'import os,json,sys\nprint(json.dumps({"file":__file__,"args":sys.argv[1:]}))\n'
    )
    return result


class BackupBundleTests(unittest.TestCase):
    def test_optional_absent_present_and_explicit_readoption_same_sha(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            supervisor = fixture(path)
            self.assertFalse(
                (supervisor.bundle(supervisor.activation()["active"]) / "drive-backup.py").exists()
            )
            with isolated(path), patch.object(c, "source", return_value=(TREE, backup_blobs())):
                self.assertEqual(supervisor.operate("adopt", NEW, "ops-1")["state"], "VERIFIED")
                reference = supervisor.activation()["active"]
                original = (supervisor.releases / NEW / "drive-backup.py").stat().st_ino
                self.assertEqual(
                    supervisor.operate("recover", NEW, "ops-2", "ops-1")["state"], "VERIFIED"
                )
                self.assertEqual(supervisor.activation()["active"]["sha"], OLD)
                self.assertEqual(supervisor.operate("adopt", NEW, "ops-3")["state"], "VERIFIED")
                self.assertEqual(supervisor.activation()["active"], reference)
                self.assertEqual(
                    (supervisor.releases / NEW / "drive-backup.py").stat().st_ino, original
                )
                self.assertEqual(supervisor.activation()["generation"], 4)

    def test_optional_hash_symlink_and_unsafe_mode_refuse(self):
        for case in ("hash", "symlink", "mode"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                supervisor = fixture(path)
                reference = supervisor.stage(NEW, TREE, backup_blobs())
                script = supervisor.releases / NEW / "drive-backup.py"
                if case == "hash":
                    script.write_bytes(b"changed")
                elif case == "symlink":
                    script.unlink()
                    script.symlink_to(supervisor.releases / NEW / "server-control.py")
                else:
                    script.chmod(0o755)
                with self.assertRaises(c.Refused):
                    supervisor.bundle(reference)

    def test_optional_git_source_absence_regular_modes_and_symlink(self):
        for mode in (None, "100644", "100755", "120000"):

            def command(args, mode=mode, **kwargs):
                if "get-url" in args:
                    return b"https://github.com/bimoool/pullup-trainer-bot.git"
                if "rev-parse" in args:
                    return TREE.encode()
                if "ls-tree" in args:
                    selected = mode if args[-1] == "deploy/drive-backup.py" else "100644"
                    return (
                        b"" if selected is None else f"{selected} blob {OLD}\t{args[-1]}\n".encode()
                    )
                if "show" in args:
                    return b"pass\n" if args[-1].endswith(".py") else b"#!/bin/bash\nexit 0\n"
                return b""

            with self.subTest(mode=mode), patch.object(c, "run", side_effect=command):
                if mode == "120000":
                    with self.assertRaises(c.Refused):
                        c.source(NEW)
                else:
                    _, result = c.source(NEW)
                    self.assertEqual("drive-backup.py" in result, mode is not None)

    def test_local_launcher_authority_no_flags_no_remote_environment(self):
        local = launcher()
        local.admit(["scheduled"], {}, 0)
        for args, environment, uid in (
            (["scheduled", "backup-20261115"], {}, 0),
            (["scheduled"], {"SSH_ORIGINAL_COMMAND": ""}, 0),
            (["scheduled"], {"SSH_CONNECTION": "host"}, 0),
            (["scheduled"], {"SSH_AUTH_SOCK": "/tmp/socket"}, 0),
            (["scheduled"], {}, 1000),
        ):
            with (
                self.subTest(args=args, environment=environment, uid=uid),
                self.assertRaises(RuntimeError),
            ):
                local.admit(args, environment, uid)
        for command in (
            f"prod-controller backup {NEW} ops-1",
            "/root/bin/control-plane-backup.py",
            f"prod-control backup {NEW} ops-1 --date=x",
        ):
            self.assertFalse(c.allowed_delegate(command))

    def test_launcher_capability_absent_and_single_snapshot_exec(self):
        local = launcher()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            supervisor = fixture(path)
            with patch.object(local.os, "execve") as execute, self.assertRaises(RuntimeError):
                local.execute(supervisor)
            execute.assert_not_called()
            before = supervisor.activation()
            with isolated(path), patch.object(c, "source", return_value=(TREE, backup_blobs())):
                supervisor.operate("adopt", NEW, "ops-1")
            selected = supervisor.activation()
            with (
                patch.object(supervisor, "activation", side_effect=[selected, before]) as observe,
                patch.object(local.os, "execve") as execute,
            ):
                local.execute(supervisor)
            self.assertEqual(observe.call_count, 1)
            executable, arguments, environment = execute.call_args.args
            self.assertEqual(executable, "/usr/bin/python3")
            self.assertEqual(
                arguments, ["python3", "-I", str(supervisor.releases / NEW / "drive-backup.py")]
            )
            self.assertEqual(set(environment), {"PATH", "HOME", "LANG"})

    def test_actual_scheduler_exec_uses_fixed_bundle_artifact_without_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            supervisor = fixture(path)
            with isolated(path), patch.object(c, "source", return_value=(TREE, backup_blobs())):
                supervisor.operate("adopt", NEW, "ops-1")
            script = """import sys
from pathlib import Path
from tools.tests.test_control_plane_backup import launcher,c
p=Path(sys.argv[1]); launcher().execute(c.Supervisor(p/"control",p/"ledger"))
"""
            result = subprocess.run(
                [sys.executable, "-c", script, directory],
                cwd=ROOT,
                capture_output=True,
                check=False,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(
                json.loads(result.stdout),
                {"file": str(supervisor.releases / NEW / "drive-backup.py"), "args": []},
            )


if __name__ == "__main__":
    unittest.main()
