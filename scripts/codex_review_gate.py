"""Read native Codex review state; never execute PR code or request an LLM run."""

import json
import os
import re
import time
import urllib.error
import urllib.request

BOT_ID = 199175422
BOT_LOGIN = "chatgpt-codex-connector[bot]"
SUMMARY = "<!-- codex-pull-request-review-summary -->"
STATE = re.compile(r"<!-- codex-review-state:v1 (\{.*\}) -->")
WAIT_SECONDS = 12 * 60
INTERVAL_SECONDS = 30


class GateError(RuntimeError):
    pass


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GateError("duplicate JSON key in review state")
        result[key] = value
    return result


def review_state(comments, repository, pr_number, head_sha):
    """Latest authentic summary wins, including pending/invalid state; default is refusal."""
    summaries = []
    for comment in comments:
        user = comment.get("user") or {}
        if (user.get("id"), user.get("login"), user.get("type")) != (BOT_ID, BOT_LOGIN, "Bot"):
            continue
        if comment.get("issue_url") != (
            f"https://api.github.com/repos/{repository}/issues/{pr_number}"
        ):
            continue
        if not (comment.get("body") or "").startswith(SUMMARY + "\n"):
            continue
        if type(comment.get("id")) is not int:
            raise GateError("invalid authentic comment id")
        summaries.append(comment)
    if not summaries:
        return "waiting for native Codex summary"
    body = max(summaries, key=lambda comment: comment["id"])["body"]
    lines = [line for line in body.splitlines() if line.startswith("<!-- codex-review-state:")]
    if len(lines) != 1 or not (match := STATE.fullmatch(lines[0])):
        raise GateError("unsupported or ambiguous native review schema")
    try:
        state = json.loads(match[1], object_pairs_hook=strict_object)
        review = state["code_review"]
        if not isinstance(review, dict):
            raise TypeError
    except (ValueError, KeyError, TypeError) as exc:
        raise GateError("invalid native review state") from exc
    if review.get("commit_sha") != head_sha:
        return "waiting for review of this exact SHA"
    status = review.get("status")
    if status in ("running", "pending", "queued", None):
        return "waiting for native Codex completion"
    if status != "completed":
        raise GateError(f"native review is not successful: {status!r}")
    any_findings = review.get("has_any_findings")
    unresolved = review.get("has_unresolved_findings")
    if type(any_findings) is not bool or type(unresolved) is not bool:
        raise GateError("completed review has unknown findings state")
    if unresolved:
        raise GateError("native review has unresolved findings")
    return "accepted"


class GitHub:
    def __init__(self, repository, token):
        self.repository = repository
        self.token = token

    def get(self, path):
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repository}/{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "turnikmen-native-review-gate",
            },
        )
        # Fixed GitHub host and validated repository/PR number; no comment data enters a URL.
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)

    def head(self, number):
        pr = self.get(f"pulls/{number}")
        if pr.get("state") != "open":
            raise GateError("PR is no longer open")
        return pr["head"]["sha"]

    def comments(self, number):
        result = []
        for page in range(1, 11):
            batch = self.get(f"issues/{number}/comments?per_page=100&page={page}")
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise GateError("comment pagination limit reached; refusing incomplete state")


def wait_for_review(
    api, repository, number, expected_sha, *, clock=time.monotonic, sleep=time.sleep
):
    deadline = clock() + WAIT_SECONDS
    while True:
        if api.head(number) != expected_sha:
            raise GateError("PR head changed; this gate is superseded")
        result = review_state(api.comments(number), repository, number, expected_sha)
        print(result, flush=True)
        if result == "accepted":
            # Close the fetch race: an update during the comments request invalidates acceptance.
            if api.head(number) != expected_sha:
                raise GateError("PR head changed during review validation")
            return
        if clock() >= deadline:
            raise GateError("timed out without an accepted native review of the current SHA")
        sleep(min(INTERVAL_SECONDS, max(0, deadline - clock())))


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise GateError("invalid repository")
    with open(os.environ["GITHUB_EVENT_PATH"]) as event_file:
        event = json.load(event_file)
    if os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch":
        number = str((event.get("inputs") or {}).get("pr_number", ""))
        expected = None
    else:
        number = str(event["pull_request"]["number"])
        expected = event["pull_request"]["head"]["sha"]
    if not re.fullmatch(r"[1-9][0-9]{0,6}", number):
        raise GateError("invalid PR number")
    api = GitHub(repository, os.environ["GH_TOKEN"])
    expected = expected or api.head(number)
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise GateError("invalid head SHA")
    print(f"Native Codex gate for PR #{number}, SHA {expected}", flush=True)
    wait_for_review(api, repository, int(number), expected)


if __name__ == "__main__":
    try:
        main()
    except (GateError, urllib.error.URLError, KeyError, ValueError) as error:
        raise SystemExit(f"Native Codex review gate refused: {error}") from None
