"""Synthetic filesystem and fake Docker checks; no SSH, credentials or database."""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "installer", ROOT / "deploy/install-staging-qa-access.py"
)
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class AccessTests(unittest.TestCase):
    def test_install_preserves_prior_policy_keys_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as name:
            home = Path(name)
            target = home / "deploy-staging-dispatch.sh"
            target.write_bytes(b"#!/bin/bash\nexit 17\n")
            target.chmod(0o755)
            keys = home / "authorized_keys"
            keys.write_bytes(b"synthetic-existing-entry\n")
            INSTALLER.install(home, b"helper", b"dispatcher")
            INSTALLER.install(home, b"helper", b"dispatcher")
            self.assertEqual(keys.read_bytes(), b"synthetic-existing-entry\n")
            self.assertEqual(
                (home / "deploy-staging-dispatch.before-qa.sh").read_bytes(),
                b"#!/bin/bash\nexit 17\n",
            )
            target.write_bytes(b"later-admin-change")
            with self.assertRaises(RuntimeError):
                INSTALLER.install(home, b"helper", b"dispatcher")
            self.assertEqual(target.read_bytes(), b"later-admin-change")

    def test_refuses_existing_unknown_helper_and_symlinks_without_mutation(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink), tempfile.TemporaryDirectory() as name:
                home = Path(name)
                target = home / "deploy-staging-dispatch.sh"
                target.write_bytes(b"old")
                qa = home / "qa-staging.sh"
                if symlink:
                    qa.symlink_to(home / "absent")
                else:
                    qa.write_bytes(b"unknown")
                with self.assertRaises(RuntimeError):
                    INSTALLER.install(home, b"helper", b"dispatcher")
                self.assertEqual(target.read_bytes(), b"old")
                self.assertFalse((home / "deploy-staging-dispatch.before-qa.sh").exists())

    def test_exact_commands_only_and_legacy_rejections_preserved(self):
        with tempfile.TemporaryDirectory() as name:
            home = Path(name)
            (home / "qa-staging.sh").write_text('#!/bin/bash\nprintf "QA:%s" "$1"\n')
            (home / "qa-staging.sh").chmod(0o755)
            legacy = home / "deploy-staging-dispatch.before-qa.sh"
            legacy.write_text("#!/bin/bash\nexit 23\n")
            legacy.chmod(0o755)
            text = (
                (ROOT / "deploy/staging-qa-access-dispatch.sh")
                .read_text()
                .replace("/home/deploy", name)
            )
            for cmd, code, output in [
                ("./qa-staging.sh provision", 0, "QA:provision"),
                ("./qa-staging.sh snapshot", 0, "QA:snapshot"),
                ("./qa-staging.sh provision; id", 23, ""),
                ("./qa-staging.sh provision other", 23, ""),
                ("bash", 23, ""),
            ]:
                with self.subTest(cmd=cmd):
                    r = subprocess.run(
                        check=False,
                        args=["bash", "-c", text],
                        env={"PATH": os.environ["PATH"], "SSH_ORIGINAL_COMMAND": cmd},
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual((r.returncode, r.stdout), (code, output))

    def test_helper_fixed_project_reserved_provisioner_and_no_extra_arguments(self):
        with tempfile.TemporaryDirectory() as name:
            home = Path(name)
            (home / "pullup-trainer-bot-staging").mkdir()
            docker = home / "docker"
            docker.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
            docker.chmod(0o755)
            text = (ROOT / "deploy/qa-staging.sh").read_text().replace("/home/deploy", name)
            env = {
                "PATH": name + ":" + os.environ["PATH"],
                "COMPOSE_FILE": "evil",
                "DOCKER_HOST": "evil",
            }
            for mode in ("provision", "snapshot"):
                r = subprocess.run(
                    check=False,
                    args=["bash", "-c", text, "qa", mode],
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("pullup-staging\nrun\n--rm\n--no-deps", r.stdout)
                self.assertIn("QA_ALLOW_STAGING=1", r.stdout)
                self.assertIn("scripts.qa.provision_staging_identities", r.stdout)
                self.assertEqual("--snapshot" in r.stdout, mode == "snapshot")
            # Existing authorized_keys may already acquire the same lock with flock.
            nested = subprocess.run(
                [
                    "flock",
                    "-n",
                    str(home / ".deploy-staging.lock"),
                    "bash",
                    "-c",
                    text,
                    "qa",
                    "provision",
                ],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(nested.returncode, 0, nested.stderr)
            r = subprocess.run(
                check=False,
                args=["bash", "-c", text, "qa", "provision", "extra"],
                env=env,
                capture_output=True,
            )
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(r.stdout, b"")
