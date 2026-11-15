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
SCHEDULED = (ROOT / "deploy/control-plane-backup.py").read_bytes()
UNITS = {name: (ROOT / "deploy/systemd" / name).read_bytes() for name in i.UNITS}


def fixture(path):
    binary, backups = path / "bin", path / "backups"
    binary.mkdir(mode=0o700)
    backups.mkdir(mode=0o700)
    (path / "units").mkdir(mode=0o700)
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


def install(binary, ledger, candidate, expected, apply=True, read_state=None):
    unit_root = binary.parent / "units"
    if read_state is None:
        read_state = lambda name: {
            "enabled": "disabled",
            "active": "inactive",
            "fragment": str(unit_root / name) if (unit_root / name).exists() else "",
            "dropins": "",
        }
    return i.install(
        c,
        binary,
        ledger,
        NEW,
        TREE,
        candidate,
        SUPERVISOR,
        LAUNCHER,
        scheduled_blob=SCHEDULED,
        unit_blobs=UNITS,
        unit_root=unit_root,
        read_state=read_state,
        dropin_roots=(unit_root, binary.parent / "runtime-units"),
        apply=apply,
        expected=expected,
    )


class InstallTests(unittest.TestCase):
    def test_loaded_service_and_timer_dropins_refuse_before_any_bootstrap_write(self):
        for selected in UNITS:
            with self.subTest(unit=selected), tempfile.TemporaryDirectory() as directory:
                binary, ledger, candidate, expected = fixture(Path(directory))
                state = lambda name, selected=selected: {
                    "enabled": "disabled",
                    "active": "inactive",
                    "fragment": "",
                    "dropins": "/run/systemd/system/" + selected + ".d/override.conf"
                    if name == selected
                    else "",
                }
                with self.assertRaisesRegex(c.Refused, "UNKNOWN_SYSTEMD_DROPINS"):
                    install(binary, ledger, candidate, expected, read_state=state)
                self.assertFalse((binary / "control-plane").exists())
                self.assertFalse((binary / "control-plane-supervisor.py").exists())

    def test_unloaded_exact_prefix_and_global_service_timer_overrides_refuse(self):
        for kind in ("service", "timer"):
            for directory_name in (
                f"pullup-drive-backup.{kind}.d",
                f"pullup-drive-.{kind}.d",
                f"pullup-.{kind}.d",
                f"{kind}.d",
            ):
                with (
                    self.subTest(folder=directory_name),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    binary, ledger, candidate, expected = fixture(Path(directory))
                    override = binary.parent / "units" / directory_name
                    override.mkdir()
                    value = (
                        "[Service]\nExecStart=\nExecStart=/root/bin/drive-backup.py\n"
                        if kind == "service"
                        else "[Timer]\nOnCalendar=\nOnCalendar=hourly\n"
                    )
                    (override / "unknown.conf").write_text(value)
                    with self.assertRaisesRegex(c.Refused, "UNKNOWN_SYSTEMD_DROPINS"):
                        install(binary, ledger, candidate, expected)
                    self.assertFalse((binary / "control-plane").exists())
                    self.assertFalse((binary / "control-plane-supervisor.py").exists())

    def test_unloaded_runtime_and_symlink_dropins_also_block_dry_run(self):
        for case in ("runtime", "symlink"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                binary, ledger, candidate, expected = fixture(Path(directory))
                runtime = binary.parent / "runtime-units"
                runtime.mkdir()
                if case == "runtime":
                    override = runtime / "pullup-drive-backup.service.d"
                    override.mkdir()
                    (override / "unknown.conf").write_text("[Service]\nExecStart=/unreviewed\n")
                else:
                    (binary.parent / "units/pullup-drive-backup.timer.d").symlink_to(
                        runtime / "missing"
                    )
                with self.assertRaisesRegex(c.Refused, "UNKNOWN_SYSTEMD_DROPINS"):
                    install(binary, ledger, candidate, expected, apply=False)
                self.assertFalse((binary / "control-plane").exists())

    def test_loaded_unit_dropin_query_failure_refuses_unknown_effective_config(self):
        from unittest.mock import patch

        def result(code, output):
            return type("Result", (), {"returncode": code, "stdout": output})()

        responses = [
            result(0, "disabled\n"),
            result(3, "inactive\n"),
            result(0, "/etc/systemd/system/pullup-drive-backup.timer\n"),
            result(1, ""),
        ]
        with (
            patch.object(i.subprocess, "run", side_effect=responses),
            self.assertRaisesRegex(RuntimeError, "SYSTEMD_STATE_UNAVAILABLE"),
        ):
            i.unit_state("pullup-drive-backup.timer")

    def test_bootstrap_provisions_only_disabled_fixed_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, ledger, candidate, expected = fixture(Path(directory))
            install(binary, ledger, candidate, expected)
            self.assertTrue((binary / "control-plane-backup.py").exists())
            self.assertTrue((binary.parent / "units/pullup-drive-backup.timer").exists())
            self.assertFalse((binary.parent / "units/timers.target.wants").exists())
            self.assertIn(
                b"ExecStart=/usr/bin/python3 -I /root/bin/control-plane-backup.py",
                (binary.parent / "units/pullup-drive-backup.service").read_bytes(),
            )

    def test_known_disabled_units_and_legacy_backup_retain_inodes(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, ledger, candidate, expected = fixture(Path(directory))
            legacy = binary / "drive-backup.py"
            legacy.write_bytes(b"preserved legacy script, never selected")
            legacy.chmod(0o700)
            candidate["drive-backup.py"] = b"# reviewed bundle script\npass\n"
            original = (legacy.stat().st_ino, legacy.read_bytes())
            for name, blob in UNITS.items():
                unit = binary.parent / "units" / name
                unit.write_bytes(blob)
                unit.chmod(0o644)
            inodes = {name: (binary.parent / "units" / name).stat().st_ino for name in UNITS}
            result = install(binary, ledger, candidate, expected)
            self.assertTrue(result["schedule_disabled"])
            self.assertEqual((legacy.stat().st_ino, legacy.read_bytes()), original)
            self.assertEqual(
                inodes, {name: (binary.parent / "units" / name).stat().st_ino for name in UNITS}
            )
            self.assertEqual(
                (binary / "control-plane/releases" / NEW / "drive-backup.py").read_bytes(),
                candidate["drive-backup.py"],
            )

    def test_enabled_active_unknown_units_fragments_and_symlinks_refuse_before_write(self):
        for case in ("enabled", "active", "unknown", "fragment", "symlink", "launcher"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                binary, ledger, candidate, expected = fixture(Path(directory))
                unit = binary.parent / "units/pullup-drive-backup.timer"
                state = {"enabled": "disabled", "active": "inactive", "fragment": "", "dropins": ""}
                if case == "enabled":
                    state["enabled"] = "enabled"
                elif case == "active":
                    state["active"] = "activating"
                elif case == "fragment":
                    state["fragment"] = "/run/systemd/transient/unknown.timer"
                elif case == "unknown":
                    unit.write_bytes(b"unknown unit")
                elif case == "symlink":
                    unit.symlink_to(binary / "authorized_keys")
                else:
                    (binary / "control-plane-backup.py").write_bytes(b"unknown launcher")
                with self.assertRaises(c.Refused):
                    install(
                        binary,
                        ledger,
                        candidate,
                        expected,
                        read_state=lambda name, state=state: state,
                    )
                self.assertFalse((binary / "control-plane").exists())
                self.assertFalse((binary / "control-plane-supervisor.py").exists())

    def test_systemd_queries_are_read_only_fixed_names(self):
        from unittest.mock import patch

        result = type("Result", (), {"returncode": 0, "stdout": "disabled\n"})()
        with patch.object(i.subprocess, "run", return_value=result) as query:
            i.unit_state("pullup-drive-backup.timer")
        self.assertEqual(
            [call.args[0] for call in query.call_args_list],
            [
                ["systemctl", "is-enabled", "pullup-drive-backup.timer"],
                ["systemctl", "is-active", "pullup-drive-backup.timer"],
                [
                    "systemctl",
                    "show",
                    "--property=FragmentPath",
                    "--value",
                    "pullup-drive-backup.timer",
                ],
                [
                    "systemctl",
                    "show",
                    "--property=DropInPaths",
                    "--value",
                    "pullup-drive-backup.timer",
                ],
            ],
        )

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
            "bootstrap-schedule-published",
            "bootstrap-unit-published",
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
