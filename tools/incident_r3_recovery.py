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
