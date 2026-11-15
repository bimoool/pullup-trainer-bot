"""Revalidate the fixed incident admission and claim execution before the existing SSH step."""

import os
import re
import urllib.error

import guarded_comment_dispatch as dispatcher
import incident_r3_recovery as incident
from server_control_client import github_api

require = dispatcher.require


def comments(api):
    result = []
    for page in range(1, 101):
        rows = api("GET", f"issues/{incident.PR_NUMBER}/comments?per_page=100&page={page}")
        require(isinstance(rows, list) and len(rows) <= 100, "incident comment listing")
        result.extend(rows)
        if len(rows) < 100:
            return result
    raise dispatcher.Refused("incident comment pagination incomplete")


def bot_comment(comment):
    author = comment.get("user", {})
    return author.get("id") == dispatcher.BOT_ID and author.get("login") == "github-actions[bot]"


def authorize_execution(api, env):
    require(
        env.get("GITHUB_REPOSITORY") == dispatcher.REPO
        and env.get("GITHUB_WORKFLOW_REF")
        == f"{dispatcher.REPO}/{incident.WORKFLOW}@refs/heads/main"
        and env.get("GITHUB_REF") == "refs/heads/main"
        and env.get("GITHUB_RUN_ATTEMPT") == "1",
        "trusted first-attempt incident workflow required",
    )
    require(
        re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", "")), "trusted workflow SHA required"
    )
    require(
        all(env.get(key.upper()) == value for key, value in incident.fixed_inputs().items()),
        "fixed incident inputs required",
    )
    request_id = env.get("INCIDENT_REQUEST_COMMENT_ID", "")
    dispatcher_id = env.get("INCIDENT_DISPATCHER_RUN_ID", "")
    current_id = env.get("GITHUB_RUN_ID", "")
    require(
        all(
            re.fullmatch(r"[1-9][0-9]{0,19}", value)
            for value in (request_id, dispatcher_id, current_id)
        ),
        "incident provenance IDs required",
    )
    repository = api("GET", "")
    owner = repository["owner"]
    comment = api("GET", f"issues/comments/{request_id}")
    require(
        comment.get("body") == incident.COMMAND
        and comment.get("id") == int(request_id)
        and comment.get("issue_url")
        == f"https://api.github.com/repos/{dispatcher.REPO}/issues/{incident.PR_NUMBER}"
        and comment.get("user", {}).get("id") == owner["id"]
        and comment.get("user", {}).get("login") == owner["login"]
        and comment.get("user", {}).get("type") == "User"
        and comment.get("author_association") == "OWNER",
        "live incident owner approval required",
    )
    require(
        isinstance(comment.get("created_at"), str)
        and bool(comment["created_at"])
        and comment.get("updated_at") == comment["created_at"],
        "original unedited incident owner command required",
    )
    dispatcher.validate_pr(
        api("GET", f"pulls/{incident.PR_NUMBER}"), incident.PR_NUMBER, incident.CANDIDATE
    )
    incident.verify_evidence(api, require)
    for run_id, workflow, event in (
        (dispatcher_id, dispatcher.DISPATCHER, "issue_comment"),
        (current_id, incident.WORKFLOW, "workflow_dispatch"),
    ):
        run = api("GET", f"actions/runs/{run_id}")
        actor_id = owner["id"] if event == "issue_comment" else dispatcher.BOT_ID
        actor_login = owner["login"] if event == "issue_comment" else "github-actions[bot]"
        require(
            run.get("id") == int(run_id)
            and run.get("path") == workflow
            and run.get("event") == event
            and run.get("head_branch") == "main"
            and run.get("head_sha") == env.get("GITHUB_SHA")
            and run.get("run_attempt") == 1
            and all(
                run.get(key, {}).get("id") == actor_id
                and run.get(key, {}).get("login") == actor_login
                for key in ("actor", "triggering_actor")
            )
            and (
                run.get("status") == "in_progress"
                or (run.get("status") == "completed" and run.get("conclusion") == "success")
            ),
            "incident workflow provenance changed",
        )
    rows = comments(api)
    claims = [
        row for row in rows if bot_comment(row) and incident.CLAIM_MARKER in row.get("body", "")
    ]
    require(len(claims) == 1, "one durable incident dispatch claim required")
    require(
        incident.request_marker(request_id, dispatcher_id) in claims[0]["body"],
        "incident claim binding",
    )
    require(
        not any(
            bot_comment(row) and incident.EXECUTION_MARKER in row.get("body", "") for row in rows
        ),
        "incident execution already claimed; no replay",
    )
    # Production workflow concurrency serializes this check-and-claim. Persist before SSH;
    # ambiguity on POST stops this run, and the durable marker blocks every subsequent run.
    claim = api(
        "POST",
        f"issues/{incident.PR_NUMBER}/comments",
        {
            "body": f"{incident.EXECUTION_MARKER}\n{incident.request_marker(request_id, dispatcher_id)}\n"
            f"Incident R3 execution reserved by rollback run {current_id}. No replay or automatic retry.\n"
            f"https://github.com/{dispatcher.REPO}/actions/runs/{current_id}",
        },
    )
    require(
        type(claim.get("id")) is int and claim["id"] > 0 and bot_comment(claim),
        "incident execution claim not persisted",
    )


def main():
    env = os.environ
    # Other manual rollback checks and incidents retain their existing server guards.
    if env.get("MODE") == "apply" and env.get("MANIFEST") == incident.MANIFEST:
        authorize_execution(github_api, env)
        print(
            "Fixed incident owner approval and execution claim verified; server guards still apply."
        )
    else:
        require(
            not env.get("INCIDENT_REQUEST_COMMENT_ID")
            and not env.get("INCIDENT_DISPATCHER_RUN_ID"),
            "incident provenance cannot select another rollback",
        )


if __name__ == "__main__":
    try:
        main()
    except (dispatcher.Refused, OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        print(
            "Incident recovery admission refused or uncertain. No SSH admission; no replay or automatic retry."
        )
        raise SystemExit(1) from None
