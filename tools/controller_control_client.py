"""Trusted-main controller admission; recovery has no ordinary-dispatcher imports."""

import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from current_checks import DEFAULT_REQUIRED, CheckRefused, ensure_green

REPO = "bimoool/pullup-trainer-bot"
BOT = {"id": 41898282, "login": "github-actions[bot]"}
ADOPT_WORKFLOW = ".github/workflows/controller-control.yml"
RECOVERY_WORKFLOW = ".github/workflows/controller-recovery.yml"
DISPATCHER = ".github/workflows/cloud-command-dispatch.yml"
SHA, OP, ID = r"[0-9a-f]{40}", r"ops-[1-9][0-9]{0,19}", r"[1-9][0-9]{0,19}"
SAFE = {
    "operation_id",
    "candidate",
    "action",
    "original",
    "state",
    "stage",
    "next_step",
    "error",
    "active_sha",
    "generation",
    "activation_unknown",
}


class Refused(Exception):
    """Never print API/SSH exception contents."""


def require(value, code):
    if not value:
        raise Refused(code)


def original_comment(comment, owner, number, text):
    require(
        comment.get("body") == text
        and comment.get("issue_url") == f"https://api.github.com/repos/{REPO}/issues/{number}"
        and all(comment.get("user", {}).get(key) == owner[key] for key in ("id", "login"))
        and comment.get("user", {}).get("type") == "User"
        and comment.get("author_association") == "OWNER"
        and isinstance(comment.get("created_at"), str)
        and bool(comment["created_at"])
        and comment.get("updated_at") == comment["created_at"],
        "ORIGINAL_OWNER_COMMENT",
    )


def repository(api):
    repo = api("GET", "")
    require(repo.get("full_name") == REPO and repo.get("default_branch") == "main", "REPOSITORY")
    return repo


def runtime(api, env, workflow, event, actor):
    require(
        env.get("GITHUB_REPOSITORY") == REPO
        and env.get("GITHUB_WORKFLOW_REF") == f"{REPO}/{workflow}@refs/heads/main"
        and env.get("GITHUB_REF") == "refs/heads/main"
        and env.get("GITHUB_RUN_ATTEMPT") == "1"
        and re.fullmatch(SHA, env.get("GITHUB_SHA", ""))
        and re.fullmatch(ID, env.get("GITHUB_RUN_ID", "")),
        "FIRST_MAIN_ATTEMPT",
    )
    run_provenance(api, env["GITHUB_RUN_ID"], workflow, event, actor, env["GITHUB_SHA"])


def run_provenance(api, identity, path, event, actor, sha):
    run = api("GET", f"actions/runs/{identity}")
    require(
        run.get("id") == int(identity)
        and run.get("repository", {}).get("full_name") == REPO
        and run.get("path") == path
        and run.get("event") == event
        and run.get("head_branch") == "main"
        and run.get("head_sha") == sha
        and run.get("run_attempt") == 1
        and all(
            run.get(role, {}).get(key) == actor[key]
            for role in ("actor", "triggering_actor")
            for key in ("id", "login")
        )
        and (
            run.get("status") == "in_progress"
            or (run.get("status") == "completed" and run.get("conclusion") == "success")
        ),
        "WORKFLOW_PROVENANCE",
    )


def eligible_pr(api, number, sha=None):
    require(type(number) is int and number > 0 and number not in {372, 374}, "PR_NUMBER")
    pr = api("GET", f"pulls/{number}")
    require(
        pr.get("number") == number
        and pr.get("head", {}).get("repo", {}).get("full_name") == REPO
        and pr.get("head", {}).get("ref", "").startswith("codex/")
        and pr.get("base", {}).get("repo", {}).get("full_name") == REPO
        and pr.get("base", {}).get("ref") == "main",
        "PR_BINDING",
    )
    if sha is not None:
        require(
            pr["head"].get("sha") == sha
            and (pr.get("state") == "open" or pr.get("merged") is True),
            "PR_HEAD",
        )


def comments(api, route):
    for page in range(1, 101):
        rows = api("GET", f"{route}?per_page=100&page={page}")
        require(isinstance(rows, list) and len(rows) <= 100, "COMMENT_LIST")
        yield from rows
        if len(rows) < 100:
            return
    raise Refused("COMMENT_LIMIT")


def bot_comment(comment):
    return all(comment.get("user", {}).get(key) == BOT[key] for key in ("id", "login"))


def adoption_gates(api, sha):
    ensure_green(api, sha, {*DEFAULT_REQUIRED, "authorization"})
    candidate = api("GET", f"git/commits/{sha}")
    main = api("GET", "commits/main")
    require(candidate["tree"]["sha"] == main["commit"]["tree"]["sha"], "TRUSTED_MAIN_TREE")


def authorize_adopt(api, env):
    owner = repository(api)["owner"]
    runtime(api, env, ADOPT_WORKFLOW, "workflow_dispatch", BOT)
    sha, operation = env.get("CANDIDATE_SHA", ""), env.get("OPERATION_ID", "")
    number, request_id = env.get("PR_NUMBER", ""), env.get("REQUEST_COMMENT_ID", "")
    require(
        re.fullmatch(SHA, sha) and re.fullmatch(ID, number) and re.fullmatch(ID, request_id),
        "INPUTS",
    )
    require(
        operation == "ops-" + request_id and env.get("OPERATION") == "adopt", "OPERATION_BINDING"
    )
    number = int(number)
    comment = api("GET", f"issues/comments/{request_id}")
    require(comment.get("id") == int(request_id), "COMMENT_ID")
    original_comment(comment, owner, number, f"/pullup server-adopt-controller {sha}")
    eligible_pr(api, number, sha)
    marker = f"<!-- pullup-server-adopt-controller-v1:{number}:{sha}:{operation} -->"
    claims = [
        row
        for row in comments(api, f"issues/{number}/comments")
        if bot_comment(row) and marker in row.get("body", "")
    ]
    require(len(claims) == 1, "DISPATCHER_CLAIM")
    origin = re.findall(r"(?:dispatcher run |actions/runs/)([1-9][0-9]*)", claims[0]["body"])
    require(len(set(origin)) == 1, "DISPATCHER_ORIGIN")
    run_provenance(api, origin[0], DISPATCHER, "issue_comment", owner, env["GITHUB_SHA"])
    adoption_gates(api, sha)
    return number, "adopt", sha, operation, None


def authorize_recovery(api, env, event):
    repo = repository(api)
    owner = repo["owner"]
    runtime(api, env, RECOVERY_WORKFLOW, "issue_comment", owner)
    require(
        event.get("action") == "created" and event.get("repository", {}).get("id") == repo["id"],
        "EVENT_REPOSITORY",
    )
    require(
        all(event.get("sender", {}).get(key) == owner[key] for key in ("id", "login")),
        "EVENT_OWNER",
    )
    issue, snapshot = event.get("issue", {}), event.get("comment", {})
    number, request_id = issue.get("number"), snapshot.get("id")
    require("pull_request" in issue and type(request_id) is int and request_id > 0, "PR_EVENT")
    match = re.fullmatch(
        rf"/pullup server-(recover-controller|controller-status) ({SHA}) ({OP})",
        snapshot.get("body", ""),
    )
    require(match is not None, "COMMAND")
    verb, sha, target = match.groups()
    eligible_pr(api, number)  # Recovery survives branch advancement/closed source PR.
    live = api("GET", f"issues/comments/{request_id}")
    require(live.get("id") == request_id, "COMMENT_ID")
    original_comment(live, owner, number, snapshot["body"])
    action = "recover" if verb == "recover-controller" else "status"
    adoption = api("GET", "issues/comments/" + target.removeprefix("ops-"))
    require(adoption.get("id") == int(target.removeprefix("ops-")), "ADOPTION_ID")
    recovery_target = re.fullmatch(
        rf"/pullup server-recover-controller {sha} ({OP})", adoption.get("body", "")
    )
    if action == "status" and recovery_target:
        original_comment(adoption, owner, number, adoption["body"])
        adoption_id = recovery_target[1].removeprefix("ops-")
        adoption = api("GET", "issues/comments/" + adoption_id)
        require(adoption.get("id") == int(adoption_id), "ADOPTION_ID")
    original_comment(adoption, owner, number, f"/pullup server-adopt-controller {sha}")
    operation = "ops-" + str(request_id) if action == "recover" else target
    require(action == "status" or operation != target, "RECOVERY_ID")
    return number, action, sha, operation, target


def reserve_execution(api, number, action, operation, target, run_id):
    marker = f"<!-- pullup-controller-execution-v1:{action}:{operation} -->"
    require(
        not any(
            bot_comment(row) and marker in row.get("body", "")
            for row in comments(api, "issues/comments")
        ),
        "EXECUTION_ALREADY_CLAIMED",
    )
    result = api(
        "POST",
        f"issues/{number}/comments",
        {
            "body": f"{marker}\nController {action} reserved for `{operation}`; original `{target or operation}`. Run https://github.com/{REPO}/actions/runs/{run_id}. No automatic replay."
        },
    )
    require(
        type(result.get("id")) is int and result["id"] > 0 and bot_comment(result),
        "EXECUTION_CLAIM_NOT_PERSISTED",
    )


def safe_receipt(raw, sha, operation):
    require(len(raw) <= 32768, "RECEIPT_SIZE")
    value = json.loads(raw)
    require(isinstance(value, dict) and set(value) <= SAFE, "RECEIPT_FIELDS")
    require(
        value.get("candidate") == sha and value.get("operation_id") == operation, "RECEIPT_BINDING"
    )
    require(value.get("state") in {"RUNNING", "VERIFIED", "FAILED", "BLOCKED"}, "RECEIPT_STATE")
    for item in value.values():
        require(
            item is None
            or type(item) in {int, bool}
            or (
                isinstance(item, str)
                and len(item) <= 180
                and re.fullmatch(r"[A-Za-z0-9:._/+ -]*", item)
            ),
            "RECEIPT_VALUE",
        )
    return value


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
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def transport(env, action, sha, operation, target):
    host, key, pin = env.get("VPS_HOST", ""), env.get("KEY", ""), env.get("HOST_KEY_SHA256", "")
    require(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host) and key and pin, "SSH_CONFIGURATION"
    )
    command = f"prod-controller {action} {sha} " + (
        f"{target} {operation}" if action == "recover" else operation
    )
    with tempfile.TemporaryDirectory(prefix="controller-ssh-") as directory:
        root = Path(directory)
        (root / "key").write_text(key + "\n")
        (root / "key").chmod(0o600)
        scan = subprocess.run(
            ["ssh-keyscan", "-T", "15", "-t", "ed25519", host],
            capture_output=True,
            timeout=20,
            check=False,
        )
        require(scan.returncode == 0 and scan.stdout, "HOST_KEY_UNAVAILABLE")
        (root / "known_hosts").write_bytes(scan.stdout)
        fingerprint = subprocess.run(
            ["ssh-keygen", "-lf", str(root / "known_hosts"), "-E", "sha256"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        lines = fingerprint.stdout.splitlines()
        require(
            fingerprint.returncode == 0
            and lines
            and all(len(line.split()) >= 2 and line.split()[1] == pin for line in lines),
            "HOST_PIN",
        )
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
                command,
            ],
            capture_output=True,
            timeout=150,
            check=False,
        )
        require(result.returncode == 0, "SSH_OUTCOME_UNKNOWN")
        return safe_receipt(result.stdout, sha, operation)


def main():
    env = os.environ
    if env.get("GITHUB_EVENT_NAME") == "issue_comment":
        with open(env["GITHUB_EVENT_PATH"], encoding="utf-8") as source_file:
            event = json.load(source_file)
        authorize = lambda: authorize_recovery(github_api, env, event)
    else:
        authorize = lambda: authorize_adopt(github_api, env)
    admission = authorize()
    number, action, sha, operation, target = admission
    if action != "status":
        reserve_execution(github_api, number, action, operation, target, env["GITHUB_RUN_ID"])
        require(authorize() == admission, "ADMISSION_CHANGED")
    try:
        result = transport(env, action, sha, operation, target)
    except (Refused, OSError, ValueError, subprocess.SubprocessError):
        result = {
            "operation_id": operation,
            "candidate": sha,
            "action": action,
            "state": "UNKNOWN",
            "next_step": "controller-status-no-replay",
        }
    print(json.dumps(result, sort_keys=True))
    github_api(
        "POST",
        f"issues/{number}/comments",
        {
            "body": f"Controller `{action}` / `{operation}` / `{sha}`.\n```json\n"
            + json.dumps(result, sort_keys=True, indent=2)
            + f"\n```\nhttps://github.com/{REPO}/actions/runs/{env['GITHUB_RUN_ID']}\nQuery the original operation; never replay adoption."
        },
    )
    require(result["state"] == "VERIFIED", "OPERATION_NOT_VERIFIED")


if __name__ == "__main__":
    try:
        main()
    except (
        Refused,
        CheckRefused,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ):
        print(
            "Controller admission refused or interrupted; inspect durable claim and operation. No automatic replay."
        )
        raise SystemExit(1) from None
