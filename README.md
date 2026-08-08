# pullup-trainer-bot

Telegram-бот-тренер по подтягиваниям (Этап 0: скелет проекта).

## Стек

Python 3.12, aiogram 3, PostgreSQL 16, SQLAlchemy 2 (async), Alembic, APScheduler,
pydantic-settings, gspread, openpyxl, pytest.

Бот работает через long polling — без вебхука, без домена и HTTPS. Webhook-режим
добавим отдельным этапом, когда появится домен и реверс-прокси.

## Запуск локально

1. Скопируйте `.env.example` в `.env` и заполните `BOT_TOKEN` (получить у [@BotFather](https://t.me/BotFather)).

   ```bash
   cp .env.example .env
   ```

2. Поднимите Postgres и приложение:

   ```bash
   docker compose up --build
   ```

3. Примените миграции (пока без таблиц, но команда должна проходить):

   ```bash
   docker compose exec app alembic upgrade head
   ```

4. Проверьте, что контейнер здоров (Docker healthcheck проверяет, что процесс бота жив):

   ```bash
   docker compose ps
   ```

5. Напишите боту `/start` в Telegram.

## Запуск на VPS

Пока тоже long polling: `docker compose up -d --build`. Домен, HTTPS и переход на
webhook — отдельный этап, когда появится VPS с доменом.

## Разработка без Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # укажите DATABASE_URL на локальный Postgres
python -m app.main
```

## Тесты

`tests/test_repositories/` и `tests/test_services/` — интеграционные, на
реальном Postgres (не моки). `tests/conftest.py` сам поднимает `db` из
docker-compose (`docker compose up -d db`), создаёт отдельную БД
`pullup_test` и прогоняет туда миграции — руками ничего готовить не нужно,
только чтобы Docker был запущен:

```bash
pytest
```

Домен (`tests/test_*.py` в корне `tests/`) — чистые unit-тесты, Postgres не
трогают вообще.

## Миграции

```bash
alembic revision --autogenerate -m "описание"
alembic upgrade head
```

## Структура проекта

```
app/
  domain/     чистая бизнес-логика прогрессии тренировок (без aiogram и SQLAlchemy)
  db/         модели (models.py), репозитории (repositories/), миграции Alembic
  bot/        хендлеры aiogram, клавиатуры, тексты, состояния FSM
  services/   подписки (subscription.py), монеты и ачивки (gamification.py);
              позже — платежи, экспорт, Google Sheets, аналитика
  workers/    фоновые задачи: напоминания, синхронизация с Google Sheets
tests/
  test_*.py            unit-тесты домена
  test_repositories/   интеграционные тесты репозиториев (реальный Postgres)
  test_services/       интеграционные тесты сервисного слоя (реальный Postgres)
```
