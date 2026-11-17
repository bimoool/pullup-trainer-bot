"""Pure target-guard regressions; never connect to a database."""

import pytest

from scripts.isolated_smoke_guard import validate_targets


def smoke_env():
    url = "postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_smoke_test"
    return {"DATABASE_URL": url, "TEST_DATABASE_URL": url, "BOT_TOKEN": "synthetic"}


def test_isolated_smoke_accepts_only_explicit_disposable_database():
    validate_targets(smoke_env())


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://pullup:pullup@production.invalid:5432/pullup_smoke_test",
        "postgresql+asyncpg://pullup:pullup@localhost:5432/pullup",
        "postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_test",
        "postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_smoke_test?host=remote",
    ],
)
def test_isolated_smoke_refuses_unsafe_targets(url):
    env = smoke_env() | {"DATABASE_URL": url, "TEST_DATABASE_URL": url}
    with pytest.raises(ValueError):
        validate_targets(env)


def test_isolated_smoke_refuses_database_mismatch_and_external_inputs():
    for override in ({"TEST_DATABASE_URL": ""}, {"STAGING_URL": "https://example.invalid"}):
        with pytest.raises(ValueError):
            validate_targets(smoke_env() | override)


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch"])
def test_isolated_smoke_refuses_untrusted_ref(event):
    env = smoke_env() | {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": event}
    with pytest.raises(ValueError):
        validate_targets(env | {"GITHUB_REF": "refs/heads/untrusted"})
    validate_targets(env | {"GITHUB_REF": "refs/heads/main"})
