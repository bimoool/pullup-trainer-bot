"""No server or user data: fixed command, resource and durable-receipt contracts."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
