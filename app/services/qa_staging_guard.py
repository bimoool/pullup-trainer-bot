"""Positive identification of the STAGING environment for QA-only tooling (fail closed).

Single definition used by the staging bot's admin «🧪 Fresh reset (staging)» (app/services/qa_fresh_reset.py)
and by scripts/qa/provision_staging_identities.py. Production must never pass: anything that cannot be
positively identified as staging is refused, including an empty or partial configuration.

Signals are the ones the running staging containers already have through the canonical config
(app.config.settings ← .env; see .env.staging.example): the database name and the Mini App host. The live
connection's current_database() is checked separately by the caller (qa_fresh_reset), so a config that lies
about the database is caught too.
"""

import os
from dataclasses import dataclass
from urllib.parse import urlparse

PROD_DB_NAMES = frozenset({"pullup", "postgres"})
FORBIDDEN_DB_FRAGMENTS = ("prod", "test")
PROD_HOSTS = frozenset({"app.bimoool.com"})


class NotStagingError(RuntimeError):
    """The environment is not positively identified as staging."""


@dataclass(frozen=True)
class StagingEnvironment:
    db_name: str
    mini_app_host: str


def database_name(database_url: str) -> str:
    return urlparse(database_url.replace("+asyncpg", "")).path.lstrip("/")


def identify_staging(*, database_url: str, mini_app_url: str, postgres_db: str | None) -> StagingEnvironment:
    """Pure: return the identified staging environment or raise NotStagingError (reason in the message)."""
    if not database_url:
        raise NotStagingError("DATABASE_URL is not set")
    db_name = database_name(database_url)
    if "staging" not in db_name:
        raise NotStagingError(f"database name {db_name!r} does not contain 'staging'")
    if db_name in PROD_DB_NAMES or any(fragment in db_name for fragment in FORBIDDEN_DB_FRAGMENTS):
        raise NotStagingError(f"database name {db_name!r} looks like prod/test")
    if postgres_db and postgres_db != db_name:
        raise NotStagingError("POSTGRES_DB and DATABASE_URL disagree")
    if not mini_app_url:
        raise NotStagingError("MINI_APP_URL is not set (cannot confirm the staging host)")
    host = urlparse(mini_app_url).hostname or ""
    if host in PROD_HOSTS or not host.startswith("staging."):
        raise NotStagingError(f"MINI_APP_URL host {host!r} is not a staging host")
    return StagingEnvironment(db_name=db_name, mini_app_host=host)


def identify_running_staging() -> StagingEnvironment:
    """The running process's environment via the canonical settings (raises NotStagingError)."""
    from app.config import settings

    return identify_staging(
        database_url=settings.database_url, mini_app_url=settings.mini_app_url,
        postgres_db=os.environ.get("POSTGRES_DB"),
    )


def is_running_staging() -> bool:
    try:
        identify_running_staging()
    except NotStagingError:
        return False
    return True
