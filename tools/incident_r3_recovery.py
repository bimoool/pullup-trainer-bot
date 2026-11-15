"""Fixed evidence and inputs for the single reviewed November 15 recovery incident."""

CANDIDATE = "e9f32dd194aab140f63c445e0c2d2eddf59b2b91"
PR_NUMBER = 399
MANIFEST = "/root/backups/prod-pre-e9f32dd-20261115T075403Z.manifest"
CONFIRM = "ROLLBACK-R3-prod-e9f32dd-20261115T075403Z-247039"
COMMAND = f"/pullup incident-r3-apply {CANDIDATE} {CONFIRM}"
WORKFLOW = ".github/workflows/production-rollback.yml"
EVIDENCE_HEAD = "34176de72e42ebdb9e964dff1407af65ebfb4204"
FAILED_RUN = 43691971076
CHECK_RUN = 43692580932
CLAIM_MARKER = f"<!-- pullup-incident-r3-apply-v1:{PR_NUMBER}:{CANDIDATE} -->"
EXECUTION_MARKER = f"<!-- pullup-incident-r3-execution-v1:{FAILED_RUN} -->"


def fixed_inputs():
    return {"kind": "R3", "manifest": MANIFEST, "mode": "apply", "confirm": CONFIRM}


def request_marker(comment_id, dispatcher_id):
    return f"<!-- pullup-incident-r3-request-v1:{comment_id}:{dispatcher_id} -->"


def verify_evidence(api, require):
    # These exact run/job pairs were reviewed separately. Never read logs or dumps.
    # A rerun changes the latest attempt/job identity and requires a fresh review.
    for run_id, job_id, workflow, conclusion in (
        (FAILED_RUN, 132744343548, ".github/workflows/production-deploy.yml", "failure"),
        (CHECK_RUN, 132746139599, WORKFLOW, "success"),
    ):
        run = api("GET", f"actions/runs/{run_id}")
        require(
            run.get("id") == run_id
            and run.get("path") == workflow
            and run.get("event") == "workflow_dispatch"
            and run.get("head_branch") == "main"
            and run.get("head_sha") == EVIDENCE_HEAD
            and run.get("run_attempt") == 1
            and run.get("status") == "completed"
            and run.get("conclusion") == conclusion,
            "incident evidence run changed or unavailable",
        )
        result = api("GET", f"actions/runs/{run_id}/jobs?filter=latest&per_page=100")
        jobs = result.get("jobs", [])
        require(result.get("total_count") == 1 and len(jobs) == 1, "incident job topology")
        job = jobs[0]
        require(
            job.get("id") == job_id
            and job.get("run_id") == run_id
            and job.get("status") == "completed"
            and job.get("conclusion") == conclusion,
            "incident latest job changed or unavailable",
        )


# A separately authorized delivery recovery. The original failure's HTTP/guard cause is UNKNOWN.
ORIGINAL_REQUEST = 6895994270
ORIGINAL_DISPATCHER = 43724033626
REFUSED_RUN = 43724053051
REFUSED_JOB = 132841996080
ORIGINAL_HEAD = "226c505956a30a720e585c4aa723cd936a408f2a"
RECOVERY_COMMAND = (
    f"/pullup incident-r3-recover {CANDIDATE} {CONFIRM} "
    f"{ORIGINAL_REQUEST} {ORIGINAL_DISPATCHER} {REFUSED_RUN}"
)
RECOVERY_MARKER = f"<!-- pullup-incident-r3-recovery-v1:{REFUSED_RUN} -->"
REPO = "bimoool/pullup-trainer-bot"
BOT_ID = 41898282


def recovery_marker(comment_id, dispatcher_id):
    return f"<!-- pullup-incident-r3-recovery-request-v1:{comment_id}:{dispatcher_id} -->"


def bot_comment(comment):
    author = comment.get("user", {})
    return author.get("id") == BOT_ID and author.get("login") == "github-actions[bot]"


def comments(api, require):
    result = []
    for page in range(1, 101):
        rows = api("GET", f"issues/{PR_NUMBER}/comments?per_page=100&page={page}")
        require(isinstance(rows, list) and len(rows) <= 100, "incident comment listing")
        result.extend(rows)
        if len(rows) < 100:
            return result
    require(False, "incident comment pagination incomplete")


def owner_comment(comment, owner, comment_id, body, require):
    require(
        comment.get("id") == int(comment_id)
        and comment.get("body") == body
        and comment.get("issue_url") == f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}"
        and comment.get("user", {}).get("id") == owner["id"]
        and comment.get("user", {}).get("login") == owner["login"]
        and comment.get("user", {}).get("type") == "User"
        and comment.get("author_association") == "OWNER"
        and isinstance(comment.get("created_at"), str)
        and bool(comment["created_at"])
        and comment.get("updated_at") == comment["created_at"],
        "incident immutable owner approval required",
    )


def trusted_run(api, require, run_id, workflow, event, actor, head, terminal=None):
    run = api("GET", f"actions/runs/{run_id}")
    require(
        run.get("id") == int(run_id)
        and run.get("path") == workflow
        and run.get("event") == event
        and run.get("head_branch") == "main"
        and run.get("head_sha") == head
        and run.get("run_attempt") == 1
        and all(
            run.get(key, {}).get("id") == actor["id"]
            and run.get(key, {}).get("login") == actor["login"]
            for key in ("actor", "triggering_actor")
        )
        and (
            (run.get("status") == "completed" and run.get("conclusion") == terminal)
            if terminal
            else (
                run.get("status") == "in_progress"
                or (run.get("status") == "completed" and run.get("conclusion") == "success")
            )
        ),
        "incident workflow provenance changed",
    )


def verify_recovery(api, require, owner, recovery_id=None, dispatcher_id=None):
    """GET only: prove the original delivery terminated before its one SSH step."""
    owner_comment(
        api("GET", f"issues/comments/{ORIGINAL_REQUEST}"),
        owner,
        ORIGINAL_REQUEST,
        COMMAND,
        require,
    )
    trusted_run(
        api,
        require,
        ORIGINAL_DISPATCHER,
        ".github/workflows/cloud-command-dispatch.yml",
        "issue_comment",
        owner,
        ORIGINAL_HEAD,
        "success",
    )
    trusted_run(
        api,
        require,
        REFUSED_RUN,
        WORKFLOW,
        "workflow_dispatch",
        {"id": BOT_ID, "login": "github-actions[bot]"},
        ORIGINAL_HEAD,
        "failure",
    )
    result = api("GET", f"actions/runs/{REFUSED_RUN}/jobs?filter=latest&per_page=100")
    jobs = result.get("jobs", [])
    require(result.get("total_count") == 1 and len(jobs) == 1, "incident refused job topology")
    job = jobs[0]
    require(
        job.get("id") == REFUSED_JOB
        and job.get("run_id") == REFUSED_RUN
        and job.get("run_attempt") == 1
        and job.get("name") == "rollback"
        and job.get("status") == "completed"
        and job.get("conclusion") == "failure",
        "incident refused latest job changed",
    )
    expected_steps = [
        ("Set up job", "success"),
        ("Run actions/checkout@v4", "success"),
        ("Validate inputs", "success"),
        ("Revalidate fixed incident approval and reserve execution before SSH", "failure"),
        ("Revalidate R1 owner command and reserve execution before SSH", "skipped"),
        ("Guarded rollback R3 apply", "skipped"),
        ("Remove key", "success"),
        ("Post Run actions/checkout@v4", "success"),
        ("Complete job", "success"),
    ]
    steps = job.get("steps", [])
    require(
        len(steps) == len(expected_steps)
        and all(
            step.get("name") == name
            and step.get("status") == "completed"
            and step.get("conclusion") == conclusion
            for step, (name, conclusion) in zip(steps, expected_steps)
        ),
        "incident original SSH was not proven skipped",
    )
    rows = comments(api, require)
    claims = [r for r in rows if bot_comment(r) and CLAIM_MARKER in r.get("body", "")]
    require(len(claims) == 1, "one durable incident dispatch claim required")
    require(
        request_marker(ORIGINAL_REQUEST, ORIGINAL_DISPATCHER) in claims[0]["body"],
        "incident original claim binding",
    )
    require(
        not any(bot_comment(r) and EXECUTION_MARKER in r.get("body", "") for r in rows),
        "incident execution already claimed; no replay",
    )
    require(
        sum(bot_comment(r) and RECOVERY_MARKER in r.get("body", "") for r in rows) <= 1,
        "incident multiple recovery dispatch claims",
    )
    if recovery_id is not None:
        owner_comment(
            api("GET", f"issues/comments/{recovery_id}"),
            owner,
            recovery_id,
            RECOVERY_COMMAND,
            require,
        )
        recovery_claims = [
            r for r in rows if bot_comment(r) and RECOVERY_MARKER in r.get("body", "")
        ]
        require(len(recovery_claims) == 1, "one durable incident recovery claim required")
        require(
            recovery_marker(recovery_id, dispatcher_id) in recovery_claims[0]["body"],
            "incident recovery claim binding",
        )
    return rows
