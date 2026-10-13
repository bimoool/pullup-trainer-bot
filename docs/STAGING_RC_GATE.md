# Общий gate release-кандидата #322 + #323

Полный gate запускается **только после независимого CLOSED по #322** и **по одному прогону за раз** (общая БД и порт
8001 — два параллельных прогона перетирают друг другу сид). Ниже — подготовленные команды; focused-проверки
(сид, build/unit, specs обеих веток) уже прогнаны на кандидате и записаны в checkpoint.

## Изолированная БД (отдельный кластер, не docker-compose проекта и не staging)

```bash
PGB=/usr/lib/postgresql/16/bin            # или любой postgres 16
mkdir -p /var/tmp/pgrc && chown <user> /var/tmp/pgrc
$PGB/initdb -D /var/tmp/pgrc/data -U pullup --auth=trust
$PGB/pg_ctl -D /var/tmp/pgrc/data -o "-p 54329 -k /var/tmp/pgrc -c listen_addresses=127.0.0.1" -l /var/tmp/pgrc/pg.log -w start
psql -h 127.0.0.1 -p 54329 -U pullup -d postgres -c "create database pullup;"       # нужна для conftest (создаёт pullup_test)
psql -h 127.0.0.1 -p 54329 -U pullup -d postgres -c "create database pullup_e2e;"
```

Порт 54329 выбран, чтобы не пересекаться с dev-БД compose (эфемерный порт) и чужими проектами на VPS.
Остановка и удаление: `pg_ctl -D /var/tmp/pgrc/data stop && rm -rf /var/tmp/pgrc`.

## Окружение

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev,web]"      # проект — Python 3.12
(cd webapp-frontend && npm ci) && (cd webapp-frontend/e2e && npm ci)
```

## 1. Python: lint + весь pytest

```bash
export BOT_TOKEN=ci-test-token
export TEST_DATABASE_URL="postgresql+asyncpg://pullup@127.0.0.1:54329/pullup_test"
export DATABASE_URL="$TEST_DATABASE_URL"
.venv/bin/ruff check app/ tests/ scripts/          # CI-команда; на BASE уже есть 30 замечаний — сравнивать с BASE, не с нулём
.venv/bin/pytest -q                                 # миграции гоняет фикстура test_dsn; отдельный alembic до pytest не нужен
```

## 2. Фронтенд: build + unit

```bash
cd webapp-frontend
npm run build          # tsc -b && vite build
npm run test:unit      # node --test
npm run test:vectors   # vitest (live engine vectors)
```

## 3. Seed integrity

```bash
.venv/bin/pytest -q tests/test_scripts/test_e2e_seed_integrity.py tests/test_scripts/test_e2e_seed_stepper_time.py
```

## 4. Полный Playwright (один прогон)

```bash
export DATABASE_URL="postgresql+asyncpg://pullup@127.0.0.1:54329/pullup_e2e" BOT_TOKEN=e2e-test-token ADMIN_IDS="900010,900011,900012"
export PATH="$PWD/.venv/bin:$PATH" PYTHON="$PWD/.venv/bin/python"
alembic upgrade head
nohup uvicorn app.web.main:app --port 8001 > uvicorn.log 2>&1 &
until curl -sf http://127.0.0.1:8001/health; do sleep 1; done
scripts/e2e_seed_all.sh                  # ~10+ мин: каждый сид — отдельный процесс
cd webapp-frontend/e2e && E2E_BASE_URL=http://127.0.0.1:8001 npm test
```

Chromium уже есть в `/opt/pw-browsers` (`PLAYWRIGHT_BROWSERS_PATH`); `playwright install` не запускать.

Focused-подмножество (то, что запускалось до CLOSED #322), из `webapp-frontend/e2e`:

```bash
E2E_BASE_URL=http://127.0.0.1:8001 npx playwright test \
  scenarios/course-v5-engine.spec.ts scenarios/live-engine-v2.spec.ts \
  scenarios/fix-wave1/ui-clarity.spec.ts scenarios/fix-wave1/expired-free-pullups.spec.ts \
  scenarios/fix-wave1/expired-course-gate.spec.ts
```

Перед повторным прогоном переприменить сид (`scripts/e2e_seed_all.sh`): сценарии меняют состояние пользователей.
