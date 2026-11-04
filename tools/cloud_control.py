"""Cloud operator entry point; server credentials remain in GitHub Actions.

Only read-only staging preflight and synthetic staging QA are dispatchable here.
Production release continues through the guarded production runbook.
"""

import argparse
import json
import os
import re
import subprocess
import sys

REPOSITORY = "bimoool/pullup-trainer-bot"
PREFIX = f"repos/{REPOSITORY}/actions"


def plan(argv: list[str]) -> tuple[str, str, dict | None]:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("access-check", help="Read workflow registration; no server operation")
    preflight = commands.add_parser("staging-preflight", help="Read-only server preflight")
    preflight.add_argument("--sha", required=True)
    commands.add_parser(
        "staging-qa", help="Run full journeys using existing synthetic QA identities"
    )
    status = commands.add_parser("status", help="Read a workflow run; no log download")
    status.add_argument("run_id")
    args = parser.parse_args(argv)
    if args.command == "access-check":
        return "GET", f"{PREFIX}/workflows?per_page=100", None
    if args.command == "status":
        if not re.fullmatch(r"[1-9][0-9]*", args.run_id):
            parser.error("run_id must be a positive integer")
        return "GET", f"{PREFIX}/runs/{args.run_id}", None
    if args.command == "staging-preflight":
        if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
            parser.error("sha must be exactly 40 lowercase hex characters")
        workflow = "deploy-staging-guarded.yml"
        inputs = {"sha": args.sha, "converge": "preflight", "start": "no", "users": "-"}
    else:
        workflow = "staging-qa.yml"
        inputs = {
            "journeys": "all",
            "projects": "iphone-webkit,chromium-mobile",
            "reprovision": False,
        }
    return "POST", f"{PREFIX}/workflows/{workflow}/dispatches", {"ref": "main", "inputs": inputs}


def main(argv: list[str] | None = None) -> int:
    method, endpoint, payload = plan(sys.argv[1:] if argv is None else argv)
    token = os.environ.get("PULLUP_ACTIONS_TOKEN")
    if not token:
        print(
            "BLOCKED: bind PULLUP_ACTIONS_TOKEN as a cloud runtime secret; never paste it into chat.",
            file=sys.stderr,
        )
        return 2
    env = {
        **os.environ,
        "GH_TOKEN": token,
        "GH_HOST": "github.com",
        "GH_DEBUG": "",
        "GH_PROMPT_DISABLED": "1",
    }
    command = ["gh", "api", "--hostname", "github.com", "--method", method, endpoint]
    if payload is not None:
        command += ["--input", "-"]
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload) if payload else None,
            text=True,
            capture_output=True,
            timeout=45,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        print(
            "BLOCKED: GitHub CLI unavailable or request timed out. No automatic retry.",
            file=sys.stderr,
        )
        return 2
    if result.returncode:
        # Do not publish provider diagnostics, headers, or credentials to chat/CI.
        print(
            "BLOCKED: GitHub request failed. Check api.github.com allowlist and Actions token permissions. No automatic retry.",
            file=sys.stderr,
        )
        return 2
    if payload is not None:
        print("Dispatch accepted; this is not deployment/test success.")
        print(f"https://github.com/{REPOSITORY}/actions")
    else:
        data = json.loads(result.stdout)
        if "workflows" in data:
            print(
                json.dumps(
                    [
                        {"name": w["name"], "path": w["path"], "state": w["state"]}
                        for w in data["workflows"]
                    ]
                )
            )
        else:
            print(
                json.dumps(
                    {
                        key: data.get(key)
                        for key in ("id", "html_url", "head_sha", "status", "conclusion")
                    }
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
