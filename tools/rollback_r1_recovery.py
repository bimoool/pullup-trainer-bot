"""Fixed R1 recovery admission. No app CI gate: failed releases must remain recoverable."""

import re
from datetime import datetime

WORKFLOW = ".github/workflows/production-rollback.yml"
PRODUCTION = ".github/workflows/production-deploy.yml"
ID = r"[1-9][0-9]{0,19}"


def parse(body, require):
    match = re.fullmatch(
        rf"/pullup rollback-r1-apply ([0-9a-f]{{40}}) (/root/backups/prod-pre-([0-9a-f]{{7}})-([0-9]{{8}}T[0-9]{{6}}Z)\.manifest) "
        rf"(ROLLBACK-R1-prod-([0-9a-f]{{7}})-([0-9]{{8}}T[0-9]{{6}}Z)-({ID})) ({ID}) ({ID})",
        body,
    )
    require(match is not None, "exact R1 recovery command required")
    sha, manifest, short, stamp, token, token_short, token_stamp, _, failed, check = match.groups()
    require(
        short == token_short == sha[:7] and stamp == token_stamp, "manifest-token-candidate binding"
    )
    require(failed != check, "distinct recovery evidence required")
    return sha, {
        "kind": "R1",
        "manifest": manifest,
        "mode": "apply",
        "confirm": token,
        "recovery_candidate_sha": sha,
        "recovery_failed_run_id": failed,
        "recovery_check_run_id": check,
    }


def command(sha, inputs):
    return (
        f"/pullup rollback-r1-apply {sha} {inputs['manifest']} {inputs['confirm']} "
        f"{inputs['recovery_failed_run_id']} {inputs['recovery_check_run_id']}"
    )


def marker(inputs, execution=False):
    kind = "execution" if execution else "dispatch"
    # Failed run identity is incident-wide: neither a new PR/comment/check nor a new token replays it.
    return f"<!-- pullup-r1-{kind}-v1:{inputs['recovery_failed_run_id']} -->"


def request_marker(request, dispatch):
    return f"<!-- pullup-r1-request-v1:{request}:{dispatch} -->"


def original_comment(comment, owner, number, body, require):
    require(
        comment.get("body") == body
        and comment.get("issue_url")
        == f"https://api.github.com/repos/bimoool/pullup-trainer-bot/issues/{number}"
        and comment.get("user", {}).get("id") == owner["id"]
        and comment.get("user", {}).get("login") == owner["login"]
        and comment.get("user", {}).get("type") == "User"
        and comment.get("author_association") == "OWNER"
        and isinstance(comment.get("created_at"), str)
        and bool(comment["created_at"])
        and comment.get("updated_at") == comment["created_at"],
        "original unedited owner command required",
    )


def trusted_run(api, run_id, workflow, conclusion, require, bot_id):
    run = api("GET", f"actions/runs/{run_id}")
    require(
        run.get("id") == int(run_id)
        and run.get("path") == workflow
        and run.get("event") == "workflow_dispatch"
        and run.get("head_branch") == "main"
        and re.fullmatch(r"[0-9a-f]{40}", run.get("head_sha", ""))
        and run.get("run_attempt") == 1
        and run.get("status") == "completed"
        and run.get("conclusion") == conclusion
        and all(
            run.get(key, {}).get("id") == bot_id and run[key].get("login") == "github-actions[bot]"
            for key in ["actor", "triggering_actor"]
        ),
        "trusted first-attempt recovery evidence required",
    )
    ancestry = api("GET", f"compare/{run['head_sha']}...main")
    require(
        ancestry.get("merge_base_commit", {}).get("sha") == run["head_sha"],
        "evidence must belong to trusted main history",
    )
    result = api("GET", f"actions/runs/{run_id}/jobs?filter=latest&per_page=100")
    jobs = result.get("jobs", [])
    require(result.get("total_count") == 1 and len(jobs) == 1, "recovery job topology")
    job = jobs[0]
    require(
        type(job.get("id")) is int
        and job["id"] > 0
        and job.get("run_id") == int(run_id)
        and job.get("name") == ("deploy" if workflow == PRODUCTION else "rollback")
        and job.get("status") == "completed"
        and job.get("conclusion") == conclusion,
        "latest recovery job required",
    )
    return run, job


def verify_evidence(api, sha, inputs, require, bot_id, current_run_id=None):
    # Parse again so internal/workflow input calls cannot bypass the command contract.
    _, parsed = parse(command(sha, inputs), require)
    require(all(inputs.get(k) == v for k, v in parsed.items()), "R1 input binding")
    failed, failed_job = trusted_run(
        api, inputs["recovery_failed_run_id"], PRODUCTION, "failure", require, bot_id
    )
    checked, check_job = trusted_run(
        api, inputs["recovery_check_run_id"], WORKFLOW, "success", require, bot_id
    )
    require(
        re.fullmatch(
            rf"Guarded production {sha} apply [0-9a-f]{{12}} [0-9a-f]{{12}}",
            failed.get("display_title", ""),
        ),
        "failed apply candidate binding",
    )
    require(
        checked.get("display_title") == f"Guarded rollback R1 check {inputs['manifest']}",
        "matching R1 check required",
    )
    completed = failed_job.get("completed_at")
    started = check_job.get("started_at")
    require(
        isinstance(completed, str)
        and bool(completed)
        and isinstance(started, str)
        and started > completed,
        "R1 check must execute after failed apply",
    )
    stamp = (
        inputs["manifest"]
        .removeprefix("/root/backups/prod-pre-")
        .split("-", 1)[1]
        .removesuffix(".manifest")
    )
    try:
        backup_at = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").isoformat() + "Z"
    except ValueError:
        require(False, "valid manifest timestamp required")
    require(
        isinstance(failed_job.get("started_at"), str)
        and failed_job["started_at"] <= backup_at <= completed,
        "manifest must belong to failed apply execution",
    )
    for workflow in [PRODUCTION, WORKFLOW]:
        for page in range(1, 101):
            rows = api(
                "GET",
                f"actions/workflows/{workflow.rsplit('/', 1)[1]}/runs?per_page=100&page={page}",
            )["workflow_runs"]
            require(isinstance(rows, list) and len(rows) <= 100, "recovery run listing")
            for run in rows:
                if str(run.get("id")) in {
                    inputs["recovery_failed_run_id"],
                    inputs["recovery_check_run_id"],
                    current_run_id,
                }:
                    continue
                title = run.get("display_title", "")
                if workflow == PRODUCTION and re.fullmatch(
                    r"Guarded production [0-9a-f]{40} preflight [0-9a-f]{12} [0-9a-f]{12}", title
                ):
                    continue
                if (
                    workflow == WORKFLOW
                    and title.startswith("Guarded rollback ")
                    and " check " in title
                ):
                    if title != f"Guarded rollback R1 check {inputs['manifest']}":
                        continue
                    updated = run.get("updated_at")
                    require(
                        isinstance(updated, str) and updated < check_job["started_at"],
                        "R1 check superseded by another attempt",
                    )
                    continue
                # Updated time catches reruns of old creation-ordered runs too. Unknown
                # titles/timestamps fail closed because the command may have changed live state.
                updated = run.get("updated_at")
                require(
                    isinstance(updated, str) and updated < failed_job["started_at"],
                    "recovery evidence invalidated by another production attempt",
                )
            if len(rows) < 100:
                break
        else:
            require(False, "recovery history incomplete")
    # Original failed release admission is independently bound to its candidate PR by child/dispatcher.
