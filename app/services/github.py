import re
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


# Мёрж-коммит от кнопки "Merge pull request" на GitHub — первая строка сама
# по себе нечитаема ("Merge pull request #83 from bimoool/claude/issue-82-
# ..."), но GitHub кладёт заголовок смёрженного PR второй непустой строкой
# того же сообщения (после разделяющей пустой строки) — он и есть
# человекочитаемое описание того, что раскатили (issue #84).
_MERGE_PR_LINE = re.compile(r"^Merge pull request #\d+ from \S+\s*$")
# Conventional Commits префиксы ("fix:", "feat(scope)!:" и т.п.) — не то,
# что стоит показывать пользователю бота напрямую.
_CONVENTIONAL_PREFIX = re.compile(r"^(feat|fix|chore|docs|refactor|test|style|perf|build|ci)(\([^)]*\))?!?:\s*", re.IGNORECASE)


def _strip_conventional_prefix(line: str) -> str:
    stripped = _CONVENTIONAL_PREFIX.sub("", line, count=1)
    if stripped and stripped[0].islower():
        stripped = stripped[0].upper() + stripped[1:]
    return stripped


def _normalize_commit_message(raw_message: str) -> str:
    lines = raw_message.splitlines()
    first_line = lines[0] if lines else ""
    if _MERGE_PR_LINE.match(first_line):
        pr_title = next((line.strip() for line in lines[1:] if line.strip()), None)
        if pr_title:
            return _strip_conventional_prefix(pr_title)
        return first_line
    return _strip_conventional_prefix(first_line)


def _parse_commits(data: list[dict]) -> list[CommitSummary]:
    return [
        CommitSummary(
            sha=item["sha"],
            message=_normalize_commit_message(item["commit"]["message"]),
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
