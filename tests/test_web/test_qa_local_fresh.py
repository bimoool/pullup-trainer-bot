"""The local WebKit diagnostic must refuse other targets before opening a database."""

from types import SimpleNamespace

import pytest

from scripts.qa import seed_local_fresh


@pytest.mark.parametrize(
    "database_url,token",
    [
        ("postgresql+asyncpg://pullup:pullup@db:5432/pullup_qa_fresh_local", "ci-test-token"),
        ("postgresql+asyncpg://pullup:pullup@localhost:5432/pullup", "ci-test-token"),
        ("postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_staging", "ci-test-token"),
        ("postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_qa_fresh_local", "other-token"),
    ],
)
async def test_local_seed_refuses_other_targets_before_io(monkeypatch, database_url, token):
    monkeypatch.setattr(
        seed_local_fresh, "settings", SimpleNamespace(database_url=database_url, bot_token=token)
    )

    def forbidden_session():
        pytest.fail("refused target opened a database")

    monkeypatch.setattr(seed_local_fresh, "async_session_factory", forbidden_session)
    with pytest.raises(RuntimeError, match="local fresh diagnostic requires"):
        await seed_local_fresh.main()
