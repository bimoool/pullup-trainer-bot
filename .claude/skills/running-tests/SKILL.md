---
name: running-tests
description: Как прогнать тесты этого репозитория локально и что именно проверяет CI. Использовать перед тем как отчитаться о готовности задачи, при падении pytest с ошибками подключения к базе, при настройке окружения, и всегда после изменений в app/ или webapp-frontend/.
---

# Тесты

## Локальный прогон

```bash
pip install -e ".[dev,web]"
export BOT_TOKEN=ci-test-token
export TEST_DATABASE_URL="postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_test"
export DATABASE_URL="$TEST_DATABASE_URL"
pytest -q
```

Полный набор — ~1068 тестов, около минуты на нормальной машине.

## Две ловушки с базой (обе стоили красного CI)

1. **Нужна база `pullup`, а не только `pullup_test`.** `tests/conftest.py::_ensure_database_exists`
   подключается к служебной базе `pullup` и САМ создаёт из неё `pullup_test`. Если поднять
   только `pullup_test` — весь набор падает с `InvalidCatalogNameError` (699 ошибок).
2. **Миграции отдельным шагом не нужны.** Фикстура `test_dsn` сама вызывает
   `alembic upgrade head` на тестовой базе. Отдельный `alembic upgrade head` до pytest
   падает, потому что целевой базы ещё не существует.

Без `TEST_DATABASE_URL` conftest попытается поднять `docker compose up -d db` — в CI
и в песочнице этого обычно нет, поэтому переменную задавать обязательно.

## Что гоняет CI

- `tests.yml` — `ruff check` + `ruff format --check`, `pytest`, сборка фронтенда (`npm run build`,
  включая `tsc -b`). Триггер: каждый PR и push в `main`.
- `e2e.yml` — Playwright против реально поднятого бэкенда с Postgres, сценарии
  `not_onboarded` / `first_workout` / `ready` через `scripts/e2e_seed.py`. Триггер: PR
  с изменениями в `webapp-frontend/**`, `app/web/**`, `app/db/**`, `app/domain/**`, `app/services/**`.
- `claude-code-review.yml` — авто-ревью на каждый PR.

## Правило отчётности

Ветка без PR не проверяется ничем. Закончил задачу — **открой PR** (можно draft),
это единственное, что запускает CI. Не отчитывайся «готово», пока CI не зелёный.
