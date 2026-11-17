"""R1 execution admission immediately before the unchanged forced rollback command."""

import os
import re
import urllib.error

import guarded_comment_dispatch as d
import rollback_r1_recovery as r1
from incident_r3_recovery_client import bot_comment
from server_control_client import github_api


def incident_comments(api):
    # Repository-wide claims: another PR with the same candidate cannot replay an incident.
    for page in range(1, 101):
        rows = api("GET", f"issues/comments?per_page=100&page={page}")
        d.require(isinstance(rows, list) and len(rows) <= 100, "recovery comment listing")
        yield from rows
        if len(rows) < 100:
            return
    raise d.Refused("recovery comment history incomplete")


def provenance(api, env, owner, dispatcher_id, workflow):
    for run_id, path, event, actor in [
        (dispatcher_id, d.DISPATCHER, "issue_comment", owner),
        (
            env["GITHUB_RUN_ID"],
            workflow,
            "workflow_dispatch",
            {"id": d.BOT_ID, "login": "github-actions[bot]"},
        ),
    ]:
        run = api("GET", f"actions/runs/{run_id}")
        d.require(
            run.get("id") == int(run_id)
            and run.get("path") == path
            and run.get("event") == event
            and run.get("head_branch") == "main"
            and run.get("head_sha") == env.get("GITHUB_SHA")
            and run.get("run_attempt") == 1
            and all(
                run.get(key, {}).get("id") == actor["id"]
                and run[key].get("login") == actor["login"]
                for key in ["actor", "triggering_actor"]
            )
            and (
                run.get("status") == "in_progress"
                or (run.get("status") == "completed" and run.get("conclusion") == "success")
            ),
            "trusted first-attempt workflow provenance required",
        )


def authorize_execution(api, env):
    d.require(
        env.get("GITHUB_REPOSITORY") == d.REPO
        and env.get("GITHUB_WORKFLOW_REF") == f"{d.REPO}/{r1.WORKFLOW}@refs/heads/main"
        and env.get("GITHUB_REF") == "refs/heads/main"
        and env.get("GITHUB_RUN_ATTEMPT") == "1"
        and re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", "")),
        "trusted first-attempt R1 workflow required",
    )
    inputs = {
        key: env.get(key.upper(), "")
        for key in [
            "kind",
            "manifest",
            "mode",
            "confirm",
            "recovery_candidate_sha",
            "recovery_failed_run_id",
            "recovery_check_run_id",
        ]
    }
    sha = inputs["recovery_candidate_sha"]
    number, request_id, dispatcher_id = [
        env.get(key, "")
        for key in [
            "RECOVERY_PR_NUMBER",
            "RECOVERY_REQUEST_COMMENT_ID",
            "RECOVERY_DISPATCHER_RUN_ID",
        ]
    ]
    d.require(
        all(
            re.fullmatch(r1.ID, value)
            for value in [number, request_id, dispatcher_id, env.get("GITHUB_RUN_ID", "")]
        ),
        "R1 provenance IDs required",
    )
    repository = api("GET", "")
    d.require(
        repository.get("full_name") == d.REPO and repository.get("default_branch") == "main",
        "live repository",
    )
    owner = repository["owner"]
    comment = api("GET", f"issues/comments/{request_id}")
    r1.original_comment(comment, owner, number, r1.command(sha, inputs), d.require)
    d.require(comment.get("id") == int(request_id), "live comment identity")
    d.validate_pr(api("GET", f"pulls/{number}"), int(number), sha)
    provenance(api, env, owner, dispatcher_id, r1.WORKFLOW)
    r1.verify_evidence(api, sha, inputs, d.require, d.BOT_ID, env["GITHUB_RUN_ID"])
    rows = list(incident_comments(api))
    claims = [row for row in rows if bot_comment(row) and r1.marker(inputs) in row.get("body", "")]
    d.require(
        len(claims) == 1
        and r1.request_marker(request_id, dispatcher_id) in claims[0]["body"]
        and claims[0].get("issue_url") == f"https://api.github.com/repos/{d.REPO}/issues/{number}",
        "one bound durable R1 dispatch claim required",
    )
    d.require(
        not any(
            bot_comment(row) and r1.marker(inputs, True) in row.get("body", "") for row in rows
        ),
        "R1 execution already claimed; no replay",
    )
    claim = api(
        "POST",
        f"issues/{number}/comments",
        {
            "body": f"{r1.marker(inputs, True)}\n{r1.request_marker(request_id, dispatcher_id)}\n"
            f"R1 execution reserved by rollback run {env['GITHUB_RUN_ID']}. No replay or automatic retry.\n"
            f"https://github.com/{d.REPO}/actions/runs/{env['GITHUB_RUN_ID']}"
        },
    )
    d.require(
        type(claim.get("id")) is int and claim["id"] > 0 and bot_comment(claim),
        "R1 execution claim not persisted",
    )


def main():
    env = os.environ
    if env.get("KIND") == "R1" and env.get("MODE") == "apply":
        authorize_execution(github_api, env)
    else:
        d.require(
            not any(value for key, value in env.items() if key.startswith("RECOVERY_")),
            "R1 provenance cannot select another operation",
        )


if __name__ == "__main__":
    try:
        main()
    except (d.Refused, OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        print("R1 recovery admission refused or uncertain. No SSH admission; no replay.")
        raise SystemExit(1) from None
