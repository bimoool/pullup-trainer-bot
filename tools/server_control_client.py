"""Trusted-main GitHub adapter; SSH returns only validated, anonymous JSON receipts."""

import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from guarded_comment_dispatch import (
    BOT_ID,
    REPO,
    Refused,
    command,
    green_checks,
    require,
    validate_pr,
)

WORKFLOW = ".github/workflows/server-control.yml"
SAFE_KEYS = {
    "operation_id",
    "action",
    "candidate",
    "stage",
    "state",
    "observed_at",
    "next_step",
    "error",
    "facts",
    "production_checkout",
    "candidate_present",
    "available_ram_mib",
    "free_disk_mib",
    "restore_min_ram_mib",
    "services",
    "runner_hashes",
    "app",
    "web",
    "db",
    "image",
    "health",
    "from_revision",
    "deploy-production-guarded-run.sh",
    "rollback-production-guarded.sh",
    "prod-guarded-dispatch.sh",
    "installed",
    "match",
    "fetched_once",
    "checkout_unchanged",
    "backup_sha256",
    "backup_timestamp",
    "schema_revision",
    "constraints_valid",
    "indexes_valid",
    "sql_readable",
    "isolated_network",
    "pg_memory_mib",
    "single_restore_worker",
    "production_reserve_mib",
    "external_recovery",
    "cleanup_verified",
    "fresh_backup_created",
    "required_ram_mib",
}


def safe_receipt(raw, sha, operation):
    require(len(raw) <= 32768, "receipt too large")
    value = json.loads(raw)
    require(isinstance(value, dict), "receipt object required")
    require(
        value.get("operation_id") == operation and value.get("candidate") == sha,
        "receipt attribution",
    )

    def check(item):
        if isinstance(item, dict):
            require(set(item) <= SAFE_KEYS, "unapproved receipt field")
            for field in item.values():
                check(field)
        elif isinstance(item, str):
            require(
                len(item) <= 180 and re.fullmatch(r"[A-Za-z0-9:._/+ -]*", item),
                "unapproved receipt value",
            )
        else:
            require(item is None or type(item) in {bool, int}, "unapproved receipt type")

    check(value)
    require(value.get("state") in {"RUNNING", "VERIFIED", "BLOCKED", "FAILED"}, "receipt state")
    return value


def authorize(api, env):
    require(env["GITHUB_REPOSITORY"] == REPO, "repository")
    require(
        env["GITHUB_WORKFLOW_REF"] == f"{REPO}/{WORKFLOW}@refs/heads/main",
        "trusted default workflow required",
    )
    action, sha, operation = env["OPERATION"], env["CANDIDATE_SHA"], env["OPERATION_ID"]
    number, comment_id = env["PR_NUMBER"], env["REQUEST_COMMENT_ID"]
    require(
        re.fullmatch(r"[1-9][0-9]{0,19}", number) and re.fullmatch(r"[1-9][0-9]{0,19}", comment_id),
        "numeric attribution",
    )
    require(re.fullmatch(r"ops-[1-9][0-9]{0,19}", operation), "operation ID")
    live = api("GET", "")
    require(
        live.get("full_name") == REPO and live.get("default_branch") == "main", "live repository"
    )
    comment = api("GET", f"issues/comments/{comment_id}")
    owner = live["owner"]
    require(
        comment.get("user", {}).get("id") == owner["id"]
        and comment["user"].get("login") == owner["login"],
        "owner required",
    )
    require(
        comment.get("author_association") == "OWNER" and comment["user"].get("type") == "User",
        "owner association",
    )
    require(
        comment.get("issue_url") == f"https://api.github.com/repos/{REPO}/issues/{number}",
        "comment PR binding",
    )
    op, expected_sha, _, inputs = command(comment.get("body", ""))
    require(op == "server-" + action and expected_sha == sha, "command binding")
    require(operation == (inputs["operation_id"] or "ops-" + comment_id), "operation binding")
    validate_pr(api("GET", f"pulls/{number}"), int(number), sha)
    if action in {"prepare", "restore"}:
        green_checks(api, sha)
    # A trusted dispatcher claim must exist; a direct workflow_dispatch is not an admission shortcut.
    marker = f"<!-- pullup-server-{action}-v1:{number}:{sha}:ops-{comment_id} -->"
    claim = None
    for page in range(1, 101):
        comments = api("GET", f"issues/{number}/comments?per_page=100&page={page}")
        for item in comments:
            if item.get("user", {}).get("id") == BOT_ID and marker in item.get("body", ""):
                claim = item
        if len(comments) < 100:
            break
    else:
        raise Refused("claim pagination limit")
    require(claim is not None, "dispatcher claim required")
    match = re.search(r"(?:dispatcher run |actions/runs/)([1-9][0-9]*)", claim["body"])
    require(match is not None, "dispatcher origin required")
    run = api("GET", "actions/runs/" + match[1])
    require(
        run.get("path") == ".github/workflows/cloud-command-dispatch.yml"
        and run.get("event") == "issue_comment"
        and run.get("head_branch") == "main",
        "untrusted dispatcher run",
    )
    return int(number), action, sha, operation


def github_api(method, path, body=None):
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}" + ("/" + path if path else ""),
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    # Never automatically retry a write, including a receipt comment.
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def ssh_call(root, host, action, sha, operation):
    remote = f"prod-control {action} {sha} {operation}"
    result = subprocess.run(
        [
            "ssh",
            "-i",
            str(root / "key"),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "UserKnownHostsFile=" + str(root / "known_hosts"),
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=2",
            "root@" + host,
            remote,
        ],
        capture_output=True,
        timeout=150,
        check=False,
    )
    require(result.returncode == 0, "SSH outcome uncertain; query existing operation receipt")
    return safe_receipt(result.stdout, sha, operation)


def main():
    number, action, sha, operation = authorize(github_api, os.environ)
    host = os.environ["VPS_HOST"]
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host), "host")
    require(
        os.environ.get("KEY") and os.environ.get("HOST_KEY_SHA256"),
        "existing key and pinned host fingerprint required",
    )
    with tempfile.TemporaryDirectory(prefix="pullup-control-") as directory:
        root = Path(directory)
        (root / "key").write_text(os.environ["KEY"] + "\n")
        (root / "key").chmod(0o600)
        scan = subprocess.run(
            ["ssh-keyscan", "-T", "15", "-t", "ed25519", host],
            capture_output=True,
            timeout=20,
            check=False,
        )
        require(scan.returncode == 0 and scan.stdout, "host key unavailable")
        (root / "known_hosts").write_bytes(scan.stdout)
        fingerprint = subprocess.run(
            ["ssh-keygen", "-lf", str(root / "known_hosts"), "-E", "sha256"],
            capture_output=True,
            text=True,
            check=True,
        )
        require(
            all(
                line.split()[1] == os.environ["HOST_KEY_SHA256"]
                for line in fingerprint.stdout.splitlines()
            ),
            "host key fingerprint mismatch",
        )
        try:
            result = ssh_call(root, host, action, sha, operation)
            deadline = time.monotonic() + 1100
            while result["state"] == "RUNNING" and time.monotonic() < deadline:
                time.sleep(10)
                result = ssh_call(root, host, "receipt", sha, operation)
        except (Refused, OSError, ValueError, subprocess.SubprocessError):
            result = {
                "operation_id": operation,
                "candidate": sha,
                "action": action,
                "stage": "transport",
                "state": "UNKNOWN",
                "next_step": "query-receipt-no-blind-retry",
            }
    print(json.dumps(result, sort_keys=True))
    run_url = f"https://github.com/{REPO}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    github_api(
        "POST",
        f"issues/{number}/comments",
        {
            "body": f"<!-- pullup-server-result:{operation}:{action} -->\nServer operation `{operation}` / `{action}` / `{sha}`.\n"
            + "```json\n"
            + json.dumps(result, sort_keys=True, indent=2)
            + "\n```\n"
            + run_url
            + "\nIf state is UNKNOWN/RUNNING, request server-receipt for the same operation ID. Never replay the changing command."
        },
    )
    if result["state"] != "VERIFIED":
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except (
        Refused,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ):
        # No exception strings: an SSH/HTTP exception may contain URLs, key data or response bodies.
        print(
            "Server control refused or interrupted; inspect durable operation and Actions. No automatic retry."
        )
        raise SystemExit(1) from None
