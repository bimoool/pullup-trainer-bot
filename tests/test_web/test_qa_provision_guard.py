"""The staging provisioner must refuse anything that is not clearly staging (no DB needed)."""

import pytest

from scripts.qa.provision_staging_identities import RefusedError, assert_staging_environment

GOOD = {
    "QA_ALLOW_STAGING": "1",
    "DATABASE_URL": "postgresql+asyncpg://pullup_staging:pw@db:5432/pullup_staging",
    "POSTGRES_DB": "pullup_staging",
    "MINI_APP_URL": "https://staging.app.bimoool.com",
    "BOT_TOKEN": "x",
}


def test_staging_env_is_accepted():
    assert assert_staging_environment(GOOD) == "pullup_staging"


@pytest.mark.parametrize(
    "patch",
    [
        {"QA_ALLOW_STAGING": "0"},
        {"QA_ALLOW_STAGING": None},
        {"DATABASE_URL": "postgresql+asyncpg://pullup:pw@db:5432/pullup"},
        {"DATABASE_URL": "postgresql+asyncpg://pullup:pw@db:5432/pullup_test"},
        {"DATABASE_URL": "postgresql+asyncpg://u:pw@db:5432/staging_prod_mirror"},
        {"POSTGRES_DB": "pullup"},
        {"MINI_APP_URL": "https://app.bimoool.com"},
        {"MINI_APP_URL": None},
        {"BOT_TOKEN": None},
    ],
)
def test_non_staging_env_is_refused(patch):
    env = {**GOOD, **patch}
    env = {k: v for k, v in env.items() if v is not None}
    with pytest.raises(RefusedError):
        assert_staging_environment(env)
