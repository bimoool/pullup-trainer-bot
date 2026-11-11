"""No server or user data: fixed command, resource and durable-receipt contracts."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("server_control", ROOT / "deploy/server-control.py")
t = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = t
spec.loader.exec_module(t)


class ControlTests(unittest.TestCase):
    def test_exact_command_grammar(self):
        for action in ["readiness", "prepare", "restore", "receipt"]:
            self.assertEqual(
                t.parse_args([action, "a" * 40, "ops-123"]), (action, "a" * 40, "ops-123")
            )
        for args in [
            ["apply", "a" * 40, "ops-1"],
            ["prepare", "main", "ops-1"],
            ["restore", "a" * 40, "../x"],
            ["readiness", "a" * 40, "ops-0"],
            ["prepare", "a" * 40, "ops-1", "id"],
        ]:
            with self.assertRaises(t.Refused):
                t.parse_args(args)

    def test_restore_budget_preserves_live_reserve(self):
        with self.assertRaises(t.Refused):
            t.restore_budget(477, 10000, 5)
        with self.assertRaises(t.Refused):
            t.restore_budget(900, 3100, 100)
        b = t.restore_budget(900, 10000, 100)
        self.assertGreaterEqual(b["required_ram_mib"], 400 + 256 + 128)
        self.assertGreaterEqual(b["required_disk_mib"], 3072 + 4 * 100)
        self.assertLessEqual(b["pg_memory_mib"], 256)

    def test_receipt_is_exclusive_bound_and_terminal_failures_not_replayed(self):
        with tempfile.TemporaryDirectory() as name:
            store = t.Receipts(Path(name))
            original = store.claim("ops-123", "prepare", "a" * 40)
            self.assertIsNone(original)
            store.write(
                "ops-123",
                {
                    "operation_id": "ops-123",
                    "action": "prepare",
                    "candidate": "a" * 40,
                    "stage": "fetch",
                    "state": "RUNNING",
                    "next_step": "query-receipt",
                },
            )
            self.assertEqual(store.claim("ops-123", "prepare", "a" * 40)["state"], "RUNNING")
            with self.assertRaises(t.Refused):
                store.claim("ops-123", "restore", "a" * 40)
            with self.assertRaises(t.Refused):
                store.claim("ops-123", "prepare", "b" * 40)
            store.write(
                "ops-123",
                {
                    "operation_id": "ops-123",
                    "action": "prepare",
                    "candidate": "a" * 40,
                    "stage": "fetch",
                    "state": "FAILED",
                    "next_step": "operator-review",
                },
            )
            self.assertEqual(store.claim("ops-123", "prepare", "a" * 40)["state"], "FAILED")
            self.assertEqual((Path(name) / "ops-123.json").stat().st_mode & 0o777, 0o600)

    def test_symlink_receipt_refused(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "ops-1.json").symlink_to(root / "elsewhere")
            with self.assertRaises(t.Refused):
                t.Receipts(root).claim("ops-1", "prepare", "a" * 40)

    def test_restore_container_has_only_bounded_private_tmpfs(self):
        args = t.restore_container_args("pullup-restore-ops-123", "sha256:" + "a" * 64, 512)
        joined = " ".join(args)
        for required in [
            "--network none",
            "--memory 256m",
            "--memory-swap 256m",
            "--cpus 0.5",
            "--pids-limit 128",
            "--restart no",
            "--read-only",
            "size=512m",
        ]:
            self.assertIn(required, joined)
        for forbidden in ["--env-file", "--publish", "--volume", "--privileged", "--mount"]:
            self.assertNotIn(forbidden, args)
        self.assertNotIn("pullup-trainer-bot", joined)

    def test_insufficient_capacity_never_starts_backup_or_container(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            store = t.Receipts(root)
            store.claim("ops-123", "restore", "a" * 40)
            with (
                patch.object(t, "resources", return_value=(477, 10000)),
                patch.object(t, "service", return_value=("synthetic-db", {})),
                patch.object(t, "query", return_value=str(5 * 1048576)),
                patch.object(t, "command") as command,
            ):
                t.restore_worker("a" * 40, "ops-123", store)
                command.assert_not_called()
            result = store.read("ops-123")
            self.assertEqual(result["state"], "BLOCKED")
            self.assertEqual(result["error"], "RAM_RESERVE")
            self.assertEqual(result["facts"]["available_ram_mib"], 477)
            self.assertFalse(result["facts"]["fresh_backup_created"])

    def run_restore_fixture(self, *, uncertain_create=False, cleanup_fails=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        store = t.Receipts(root)
        store.claim("ops-123", "restore", "a" * 40)
        present = False
        removed = False
        writes = []
        original_write = store.write

        def write(operation, receipt):
            writes.append((receipt["state"], removed))
            original_write(operation, receipt)

        store.write = write

        def command(args, timeout=25):
            nonlocal present, removed
            if args[:3] == ["docker", "image", "inspect"]:
                return b'["PG_MAJOR=16"]'
            if args[-3:] == ["id", "-u", "postgres"]:
                return b"999"
            if args[:2] == ["docker", "run"]:
                present = True
                if uncertain_create:
                    raise t.Refused("COMMAND_TIMEOUT")
                return b"synthetic-container"
            if args[:3] == ["docker", "container", "ls"]:
                return b"synthetic-container\n" if present else b""
            if args[:2] == ["docker", "inspect"]:
                return b"ops-123"
            if args[:3] == ["docker", "rm", "-f"]:
                if cleanup_fails:
                    raise t.Refused("COMMAND_TIMEOUT")
                present = False
                removed = True
                return b""
            if "psql" in args:
                return b"b5d8e1f3a6c9\nt\nt\n1\n"
            raise AssertionError(args)

        def run(args, **kwargs):
            if "pg_dump" in " ".join(args):
                kwargs["stdout"].write(b"synthetic-only")
                kwargs["stdout"].flush()
            code = int(not present) if args[:3] == ["docker", "container", "inspect"] else 0
            return Mock(returncode=code)

        process = Mock(returncode=0)
        process.poll.return_value = 0
        with (
            patch.object(t, "LEDGER", root),
            patch.object(t, "resources", return_value=(1200, 10000)),
            patch.object(
                t, "service", return_value=("synthetic-db", {"Image": "sha256:" + "a" * 64})
            ),
            patch.object(t, "query", side_effect=[str(5 * 1048576), "b5d8e1f3a6c9"]),
            patch.object(t, "command", side_effect=command),
            patch.object(t.subprocess, "run", side_effect=run),
            patch.object(t.subprocess, "Popen", return_value=process),
        ):
            result = t.restore_worker("a" * 40, "ops-123", store)
        return result, store.read("ops-123"), writes, present

    def test_restore_never_publishes_success_before_cleanup(self):
        result, durable, writes, present = self.run_restore_fixture()
        self.assertFalse(present)
        self.assertEqual(durable["state"], "VERIFIED")
        self.assertEqual(result, durable)
        self.assertTrue(durable["facts"]["cleanup_verified"])
        self.assertTrue(all(removed for state, removed in writes if state == "VERIFIED"))

    def test_uncertain_container_creation_is_reconciled_and_removed(self):
        result, durable, _, present = self.run_restore_fixture(uncertain_create=True)
        self.assertFalse(present)
        self.assertEqual(result, durable)
        self.assertNotEqual(durable["state"], "VERIFIED")
        self.assertTrue(durable["facts"]["cleanup_verified"])

    def test_cleanup_failure_never_publishes_success(self):
        result, durable, writes, present = self.run_restore_fixture(cleanup_fails=True)
        self.assertTrue(present)
        self.assertEqual(result, durable)
        self.assertEqual(durable["state"], "FAILED")
        self.assertEqual(durable["stage"], "cleanup")
        self.assertNotIn("VERIFIED", [state for state, _ in writes])
        self.assertFalse(durable["facts"].get("cleanup_verified", False))

    def test_fetch_timeout_reconciles_object_and_never_retries(self):
        calls = []

        def run(args, timeout=25):
            calls.append(args)
            if args[3:6] == ["remote", "get-url", "origin"]:
                return b"https://github.com/bimoool/pullup-trainer-bot.git"
            if "fetch" in args:
                raise t.Refused("COMMAND_TIMEOUT")
            return b"b" * 40

        with (
            patch.object(t, "object_present", side_effect=[False, True, True]),
            patch.object(t, "command", side_effect=run),
        ):
            result = t.prepare("a" * 40)
        self.assertTrue(result["candidate_present"])
        self.assertEqual(sum("fetch" in c for c in calls), 1)


if __name__ == "__main__":
    unittest.main()
