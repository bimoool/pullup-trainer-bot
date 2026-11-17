"""Bounded failure metadata only. Never render exceptions, URLs, bodies or credentials."""

import json
import re
import urllib.error

# Values are fixed local codes. Unrecognized guard text is deliberately UNKNOWN.
GUARDS = {
    "trusted first-attempt incident workflow required": "TRUSTED_WORKFLOW",
    "trusted workflow SHA required": "WORKFLOW_SHA",
    "fixed incident inputs required": "FIXED_INPUTS",
    "incident provenance IDs required": "PROVENANCE_IDS",
    "live incident owner approval required": "OWNER_APPROVAL",
    "original unedited incident owner command required": "UNEDITED_APPROVAL",
    "incident immutable owner approval required": "IMMUTABLE_APPROVAL",
    "incident workflow provenance changed": "RUN_PROVENANCE",
    "incident evidence run changed or unavailable": "FIXED_EVIDENCE_RUN",
    "incident job topology": "FIXED_EVIDENCE_TOPOLOGY",
    "incident latest job changed or unavailable": "FIXED_EVIDENCE_JOB",
    "incident refused job topology": "REFUSED_TOPOLOGY",
    "incident refused latest job changed": "REFUSED_JOB",
    "incident original SSH was not proven skipped": "ORIGINAL_SSH_SKIPPED",
    "one durable incident dispatch claim required": "ORIGINAL_CLAIM_COUNT",
    "incident claim binding": "CLAIM_BINDING",
    "incident original claim binding": "ORIGINAL_CLAIM_BINDING",
    "incident execution already claimed; no replay": "EXECUTION_ALREADY_CLAIMED",
    "incident multiple recovery dispatch claims": "RECOVERY_CLAIM_COUNT",
    "one durable incident recovery claim required": "RECOVERY_CLAIM_COUNT",
    "incident recovery claim binding": "RECOVERY_CLAIM_BINDING",
    "incident recovery original request binding": "ORIGINAL_REQUEST",
    "new incident dispatcher required": "NEW_DISPATCHER",
    "new incident recovery approval required": "NEW_APPROVAL",
    "trusted recovery dispatcher SHA required": "DISPATCHER_SHA",
    "incident preserved claim chain changed": "PRESERVED_CLAIM_CHAIN",
    "incident redelivery parent binding": "REDELIVERY_PARENT",
    "new incident redelivery approval required": "NEW_REDELIVERY_APPROVAL",
    "incident multiple redelivery claims": "REDELIVERY_CLAIM_COUNT",
    "one durable incident redelivery claim required": "REDELIVERY_CLAIM_COUNT",
    "incident redelivery claim binding": "REDELIVERY_CLAIM_BINDING",
    "incident redelivery already reserved; no old delivery": "REDELIVERY_ALREADY_RESERVED",
    "incident manual execution reserved; no cloud replay": "MANUAL_EXECUTION_RESERVED",
    "incident execution claim not persisted": "EXECUTION_CLAIM_RESPONSE",
    "incident comment listing": "COMMENT_LISTING",
    "incident comment pagination incomplete": "COMMENT_PAGINATION",
    "incident provenance cannot select another rollback": "INCIDENT_SELECTION",
    "PR must be open or merged": "PR_STATE",
    "SHA must equal current PR head": "PR_HEAD",
    "fork PR forbidden": "PR_REPOSITORY",
    "wrong PR base": "PR_BASE",
    "codex branch required": "PR_BRANCH",
}


# Only exact GitHub message values are classified. No text from a response is emitted.
HTTP_403_REASONS = {
    "Resource not accessible by integration": "INTEGRATION_ACCESS_DENIED",
    "Resource not accessible by personal access token": "TOKEN_ACCESS_DENIED",
    "API rate limit exceeded": "RATE_LIMIT",
    "You have exceeded a secondary rate limit. Please wait a few minutes before you try again.": "SECONDARY_RATE_LIMIT",
}
HTTP_NUMERIC_HEADERS = {
    "X-RateLimit-Remaining": ("remaining", 1000000000),
    "X-RateLimit-Limit": ("limit", 1000000000),
    "X-RateLimit-Reset": ("reset", 99999999999),
    "Retry-After": ("retry_after", 86400),
}


def http_metadata(exc, status):
    reason, limits = "UNKNOWN", {}
    if not isinstance(exc, urllib.error.HTTPError) or status != 403:
        return reason, limits
    try:
        # These four headers are numbers only. Never expose request IDs or arbitrary headers.
        headers = exc.headers or {}
        for header, (key, maximum) in HTTP_NUMERIC_HEADERS.items():
            raw = headers.get(header)
            if isinstance(raw, str) and re.fullmatch(r"0|[1-9][0-9]{0,10}", raw):
                value = int(raw)
                if value <= maximum:
                    limits[key] = value
        # Failure path only: bound the read and parse only a small JSON message enum.
        # Oversized, malformed, non-JSON and unknown provider messages remain UNKNOWN.
        raw = exc.read(4097)
        if isinstance(raw, bytes) and len(raw) <= 4096:
            payload = json.loads(raw)
            message = payload.get("message") if isinstance(payload, dict) else None
            if isinstance(message, str):
                reason = HTTP_403_REASONS.get(message, "UNKNOWN")
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        pass
    return reason, limits


class Trace:
    def __init__(self):
        self.stage = "ENVIRONMENT"

    def before(self, method, path):
        if not path:
            self.stage = "REPOSITORY"
        elif path.startswith("pulls/"):
            self.stage = "PR"
        elif method == "POST" and path.endswith("/comments"):
            self.stage = "CLAIM_WRITE"
        elif path.startswith("issues/comments/"):
            self.stage = "APPROVAL"
        elif "/comments?" in path:
            self.stage = "CLAIMS"
        elif path.startswith("actions/runs/"):
            self.stage = "JOBS" if "/jobs?" in path else "RUN"
        elif path.endswith("/dispatches"):
            self.stage = "DISPATCH"
        elif path.startswith("actions/workflows/"):
            self.stage = "WORKFLOW"
        else:
            self.stage = "OTHER"

    def report(self, exc, refused=False):
        status = exc.code if isinstance(exc, urllib.error.HTTPError) else None
        if type(status) is not int or not 100 <= status <= 599:
            status = None
        reason, limits = http_metadata(exc, status)
        return json.dumps(
            {
                "stage": self.stage,
                "guard": GUARDS.get(str(exc), "UNKNOWN") if refused else "UNKNOWN",
                "failure": "REFUSED" if refused else "HTTP" if status else "UNAVAILABLE",
                "http_status": status,
                "http_reason": reason,
                "http_limits": limits,
                "historical_cause": "UNKNOWN",
                "next_step": "RECONCILE_NO_REPLAY",
            },
            sort_keys=True,
        )
