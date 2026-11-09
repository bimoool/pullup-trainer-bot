"""Owner-comment adapter: fixed read-only staging preflight, never PR code."""

import json
import os
import re
import urllib.error
import urllib.request

REPO = "bimoool/pullup-trainer-bot"
WORKFLOW = "deploy-staging-guarded.yml"
DISPATCHER = ".github/workflows/cloud-command-dispatch.yml"
BOT_ID = 41898282  # github-actions[bot] on github.com
PROTECTED_PRS = {372, 374}


class Refused(Exception):
    """An authorization or consistency check did not pass."""


def require(condition, message):
    if not condition:
        raise Refused(message)


def authorize(event, runtime, api):
    require(runtime["repository"] == REPO, "wrong runtime repository")
    require(
        runtime["workflow_ref"] == f"{REPO}/{DISPATCHER}@refs/heads/main", "untrusted workflow ref"
    )
    require(event.get("action") == "created", "only new comments are accepted")
    repository = event.get("repository", {})
    require(
        repository.get("full_name") == REPO and repository.get("default_branch") == "main",
        "wrong repository",
    )
    issue, comment = event.get("issue", {}), event.get("comment", {})
    number = issue.get("number")
    require(
        type(number) is int and number > 0 and number not in PROTECTED_PRS, "PR is not eligible"
    )
    require("pull_request" in issue, "not a PR conversation")
    require(type(comment.get("id")) is int and comment["id"] > 0, "invalid comment")
    match = re.fullmatch(r"/pullup staging-preflight ([0-9a-f]{40})", comment.get("body", ""))
    require(match is not None, "unsupported command")
    live_repo = api("GET", "")
    require(repository.get("id") == live_repo["id"], "repository ID mismatch")
    owner = live_repo["owner"]
    actor, sender = comment.get("user", {}), event.get("sender", {})
    require(
        actor.get("id") == owner["id"] == sender.get("id"), "only repository owner may dispatch"
    )
    require(actor.get("login") == owner["login"] == sender.get("login"), "owner login mismatch")
    require(
        actor.get("type") == "User" and comment.get("author_association") == "OWNER",
        "owner association required",
    )
    live_comment = api("GET", f"issues/comments/{comment['id']}")
    require(
        live_comment.get("body") == comment["body"]
        and live_comment.get("user", {}).get("id") == owner["id"],
        "comment changed or unavailable",
    )
    sha = match.group(1)
    validate_pr(api("GET", f"pulls/{number}"), number, sha)
    workflow = api("GET", f"actions/workflows/{WORKFLOW}")
    require(
        workflow.get("path") == f".github/workflows/{WORKFLOW}"
        and workflow.get("state") == "active",
        "guarded workflow unavailable",
    )
    return number, sha


def validate_pr(pr, number, sha):
    require(pr.get("number") == number and pr.get("state") == "open", "PR must remain open")
    head, base = pr.get("head", {}), pr.get("base", {})
    require(head.get("sha") == sha, "SHA must equal current PR head")
    require(head.get("repo", {}).get("full_name") == REPO, "fork PR forbidden")
    require(
        base.get("repo", {}).get("full_name") == REPO and base.get("ref") == "main", "wrong PR base"
    )
    require(head.get("ref", "").startswith("codex/"), "codex branch required")


def dispatch(event, runtime, api):
    number, sha = authorize(event, runtime, api)
    marker = f"<!-- pullup-preflight-v1:{number}:{sha} -->"
    for page in range(1, 101):
        comments = api("GET", f"issues/{number}/comments?per_page=100&page={page}")
        require(isinstance(comments, list) and len(comments) <= 100, "invalid comment listing")
        for comment in comments:
            author = comment.get("user", {})
            if (
                author.get("id") == BOT_ID
                and author.get("login") == "github-actions[bot]"
                and marker in comment.get("body", "")
            ):
                return "duplicate: existing durable claim; not dispatched again"
        if len(comments) < 100:
            break
    else:
        raise Refused("comment pagination limit; refusing incomplete deduplication")
    validate_pr(api("GET", f"pulls/{number}"), number, sha)
    receipt = api(
        "POST",
        f"issues/{number}/comments",
        {
            "body": f"{marker}\nRead-only staging preflight reserved for `{sha}` by dispatcher run {runtime['run_id']}.\n"
            "No automatic retry: if the next request is interrupted, inspect Actions before any operator recovery."
        },
    )
    require(type(receipt.get("id")) is int and receipt["id"] > 0, "claim was not persisted")
    require(receipt.get("user", {}).get("id") == BOT_ID, "claim must be authored by GitHub Actions")
    # Recheck immediately before dispatch. No untrusted checkout or shell evaluation.
    validate_pr(api("GET", f"pulls/{number}"), number, sha)
    api(
        "POST",
        f"actions/workflows/{WORKFLOW}/dispatches",
        {
            "ref": "main",
            "inputs": {"sha": sha, "converge": "preflight", "start": "no", "users": "-"},
        },
    )
    api(
        "PATCH",
        f"issues/comments/{receipt['id']}",
        {
            "body": f"{marker}\nDispatch accepted for read-only staging preflight of `{sha}`.\n"
            f"Dispatcher run: https://github.com/{REPO}/actions/runs/{runtime['run_id']}\n"
            "Acceptance is not completion. Read the guarded workflow run and verify its exact SHA, inputs and successful conclusion."
        },
    )
    return "accepted: read-only preflight requested; completion must be independently verified"


def main():
    runtime = {
        "repository": os.environ["GITHUB_REPOSITORY"],
        "workflow_ref": os.environ["GITHUB_WORKFLOW_REF"],
        "run_id": os.environ["GITHUB_RUN_ID"],
    }
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as source:
        event = json.load(source)

    def api(method, path, body=None):
        request = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}" + (f"/{path}" if path else ""),
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={
                "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "pullup-guarded-comment-dispatch",
            },
        )
        # Intentionally no retry of POST; a durable claim remains on uncertainty.
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    try:
        print(dispatch(event, runtime, api))
    except (Refused, urllib.error.URLError, TimeoutError, ValueError, KeyError):
        # No response bodies, request headers, command body or secret values in logs.
        print(
            "Dispatch refused or interrupted. No automatic retry; inspect the durable claim and Actions."
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
