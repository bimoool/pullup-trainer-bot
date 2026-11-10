"""Fail closed before any isolated-smoke migration, seed or browser request."""

import os
from urllib.parse import urlsplit


def validate_targets(env: dict[str, str]) -> None:
    urls = [env.get(key, "") for key in ("DATABASE_URL", "TEST_DATABASE_URL")]
    if urls[0] != urls[1]:
        raise ValueError("SMOKE_DATABASE_MISMATCH")
    target = urlsplit(urls[0])
    if (
        target.scheme != "postgresql+asyncpg"
        or target.hostname not in {"localhost", "127.0.0.1"}
        or target.port not in {5432, 55435}
        or target.path != "/pullup_smoke_test"
        or target.username != "pullup"
        or target.query
        or target.fragment
    ):
        raise ValueError("SMOKE_DATABASE_REFUSED")
    if any(env.get(key) for key in ("STAGING_URL", "E2E_BASE_URL", "STAGING_BOT_TOKEN")):
        raise ValueError("SMOKE_EXTERNAL_CONFIGURATION_REFUSED")
    if not env.get("BOT_TOKEN"):
        raise ValueError("SMOKE_DISPOSABLE_TOKEN_REQUIRED")
    if env.get("GITHUB_ACTIONS") == "true":
        event = env.get("GITHUB_EVENT_NAME")
        if event not in {"pull_request", "schedule", "workflow_dispatch"}:
            raise ValueError("SMOKE_EVENT_REFUSED")
        if event != "pull_request" and env.get("GITHUB_REF") != "refs/heads/main":
            raise ValueError("SMOKE_UNTRUSTED_REF")


if __name__ == "__main__":
    try:
        validate_targets(dict(os.environ))
    except (ValueError, TypeError):
        raise SystemExit("SMOKE_TARGET_GUARD_FAILED") from None
    print("SMOKE_TARGET_GUARD_PASSED")
