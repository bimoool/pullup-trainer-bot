"""Execute the actual workflow shell under bash -e with a failing synthetic browser."""

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    ("release-qa.yml", "Complete current v2 release suite (no filter or retry input)"),
    ("e2e.yml", "Diagnose exact fresh journey (no retries, real local API)"),
]


def workflow_script(filename, step):
    content = (ROOT / ".github/workflows" / filename).read_text()
    block = content.split(f"      - name: {step}\n", 1)[1].split("      - name:", 1)[0]
    return textwrap.dedent(block.split("        run: |\n", 1)[1])


class FailureReportingTest(unittest.TestCase):
    def test_actual_workflows_report_safely_and_preserve_browser_exit_under_errexit(self):
        for workflow, step in CASES:
            for status in (0, 23):
                with self.subTest(workflow=workflow, status=status), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    binary = root / "npx"
                    binary.write_text(
                        "#!/bin/bash\n"
                        "mkdir -p test-results\n"
                        "echo '{\"schema\":1,\"status\":\"synthetic\"}' > test-results/release-status.json\n"
                        "echo 'synthetic-launch-credential-must-stay-private'\n"
                        f"exit {status}\n"
                    )
                    binary.chmod(0o700)
                    result = subprocess.run(
                        ["bash", "-e", "-o", "pipefail", "-c", workflow_script(workflow, step)],
                        cwd=root,
                        env={
                            **os.environ,
                            "PATH": f"{root}:{os.environ['PATH']}",
                            "RUNNER_TEMP": str(root),
                            "STAGING_PROJECT": "iphone-webkit",
                            "STAGING_BOT_TOKEN": "ci-test-token",
                        },
                        text=True,
                        capture_output=True,
                        timeout=10,
                    )
                    self.assertEqual(result.returncode, status, result.stderr)
                    self.assertIn('"schema":1', result.stdout)
                    self.assertIn(f"exit={status}", result.stdout)
                    self.assertNotIn("synthetic-launch-credential", result.stdout + result.stderr)
                    logs = list(root.glob("*playwright.log")) + list(root.glob("release-qa.log"))
                    self.assertEqual(len(logs), 1)
                    self.assertIn("synthetic-launch-credential", logs[0].read_text())


if __name__ == "__main__":
    unittest.main()
