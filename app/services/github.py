from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import aiohttp

GITHUB_API_BASE = "https://api.github.com"


@dataclass(frozen=True)
class CommitSummary:
    sha: str
    message: str
    author: str
    committed_at: datetime


@dataclass(frozen=True)
class IssueSummary:
    number: int
    title: str
    labels: tuple[str, ...]


class GitHubClientProtocol(Protocol):
    """Форма, против которой тестируется app/workers/weekly_digest.py —
    реальный GitHub API в тестах не участвует, только фейковая реализация
    (тот же приём, что RobokassaClientProtocol в app/services/robokassa.py)."""

    async def list_commits_since(self, since: datetime) -> list[CommitSummary]: ...

    async def list_open_issues(self) -> list[IssueSummary]: ...


def _commit_author_label(item: dict) -> str:
    author = item.get("author")
    if author and author.get("login"):
        return author["login"]
    return item["commit"]["author"]["name"]


def _parse_commits(data: list[dict]) -> list[CommitSummary]:
    return [
        CommitSummary(
            sha=item["sha"],
            message=item["commit"]["message"].splitlines()[0],
            author=_commit_author_label(item),
            committed_at=datetime.fromisoformat(item["commit"]["author"]["date"]),
        )
        for item in data
    ]


def _parse_issues(data: list[dict]) -> list[IssueSummary]:
    # GET /issues отдаёт и настоящие issues, и PR вперемешку — в терминах
    # GitHub API PR это тоже issue "под капотом". У PR есть ключ
    # pull_request, у настоящих issues его нет. Без фильтра "что в работе"
    # засорилось бы код-ревью активностью, не имеющей отношения к
    # продуктовым задачам.
    return [
        IssueSummary(
            number=item["number"], title=item["title"],
            labels=tuple(label["name"] for label in item["labels"]),
        )
        for item in data if "pull_request" not in item
    ]


class GitHubClient:
    """Тонкая обёртка над GitHub REST API — без бизнес-логики форматирования
    (см. app/workers/weekly_digest.py), только запрос и разбор ответа.
    Процесс бота на сервере не имеет ни .git, ни gh CLI (деплой-образ
    копирует только app/, см. CLAUDE.md) — единственный путь к истории
    коммитов и issues отсюда, живой HTTP с токеном из app.config.settings.
    github_token (fine-grained PAT, Contents:read + Issues:read, один
    репозиторий)."""

    def __init__(self, *, token: str, owner: str, repo: str) -> None:
        self._token = token
        self._owner = owner
        self._repo = repo

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def list_commits_since(self, since: datetime) -> list[CommitSummary]:
        url = f"{GITHUB_API_BASE}/repos/{self._owner}/{self._repo}/commits"
        # since — GitHub принимает только UTC ISO8601 с "Z", не смещение.
        # per_page=100 — без полной пагинации: для еженедельного дайджеста
        # (даже с учётом первого прогона без last_digest_sent_at, когда
        # диапазон шире, см. DEFAULT_LOOKBACK_DAYS) сотни коммитов за раз
        # маловероятны, а показываем всё равно не больше MAX_COMMITS_SHOWN.
        params = {"since": since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "per_page": "100"}
        async with (
            aiohttp.ClientSession() as http,
            http.get(url, headers=self._headers(), params=params) as response,
        ):
            response.raise_for_status()
            data = await response.json()
        return _parse_commits(data)

    async def list_open_issues(self) -> list[IssueSummary]:
        url = f"{GITHUB_API_BASE}/repos/{self._owner}/{self._repo}/issues"
        params = {"state": "open", "per_page": "100"}
        async with (
            aiohttp.ClientSession() as http,
            http.get(url, headers=self._headers(), params=params) as response,
        ):
            response.raise_for_status()
            data = await response.json()
        return _parse_issues(data)
