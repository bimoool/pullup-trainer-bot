"""_parse_commits/_parse_issues — разбор ответа GitHub REST API (мок
HTTP-ответов канонными JSON-телами, тот же приём, что test_robokassa_
client.py для _parse_operation_state: реальная сеть не участвует, только
чистые функции разбора, actual HTTP-запрос в list_commits_since/
list_open_issues остаётся неявно доверенным, как и get_operation_state
там же)."""

from datetime import UTC, datetime

from app.services.github import _parse_commits, _parse_issues


def _commit_item(*, sha: str = "abc123", message: str = "Fix bug", login: str | None = "bimoool") -> dict:
    item = {
        "sha": sha,
        "commit": {
            "message": message,
            "author": {"name": "Kirill", "date": "2026-08-24T12:34:56Z"},
        },
    }
    if login is not None:
        item["author"] = {"login": login}
    else:
        item["author"] = None
    return item


def test_parse_commits_extracts_sha_message_author_and_date():
    data = [_commit_item(sha="deadbeef", message="Fix the thing", login="bimoool")]

    [commit] = _parse_commits(data)

    assert commit.sha == "deadbeef"
    assert commit.message == "Fix the thing"
    assert commit.author == "bimoool"
    assert commit.committed_at == datetime(2026, 8, 24, 12, 34, 56, tzinfo=UTC)


def test_parse_commits_uses_only_first_line_of_multiline_message():
    data = [_commit_item(message="Fix the thing\n\nLonger explanation of why.\nMore detail.")]

    [commit] = _parse_commits(data)

    assert commit.message == "Fix the thing"


def test_parse_commits_falls_back_to_commit_author_name_when_no_github_account_linked():
    # GitHub author бывает null — коммит сделан адресом почты, не привязанным
    # ни к какому GitHub-аккаунту (например, коммит до подключения GitHub
    # к email в git config).
    data = [_commit_item(login=None)]

    [commit] = _parse_commits(data)

    assert commit.author == "Kirill"


def _issue_item(*, number: int = 1, title: str = "Bug", labels: list[str] | None = None, is_pr: bool = False) -> dict:
    item = {
        "number": number,
        "title": title,
        "labels": [{"name": label} for label in (labels or [])],
    }
    if is_pr:
        item["pull_request"] = {"url": "https://api.github.com/..."}
    return item


def test_parse_issues_extracts_number_title_and_labels():
    data = [_issue_item(number=8, title="Формула прогрессии v4", labels=["done"])]

    [issue] = _parse_issues(data)

    assert issue.number == 8
    assert issue.title == "Формула прогрессии v4"
    assert issue.labels == ("done",)


def test_parse_issues_filters_out_pull_requests():
    """GET /issues отдаёт issues и PR вперемешку — у PR есть ключ
    pull_request. Без этого фильтра "что в работе" замусорилось бы
    код-ревью активностью."""
    data = [
        _issue_item(number=1, title="Настоящий issue"),
        _issue_item(number=2, title="На самом деле PR", is_pr=True),
    ]

    issues = _parse_issues(data)

    assert [i.number for i in issues] == [1]


def test_parse_issues_handles_no_labels():
    data = [_issue_item(number=1, title="Без меток", labels=[])]

    [issue] = _parse_issues(data)

    assert issue.labels == ()
