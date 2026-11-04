# Воспроизводимые Python-зависимости

Для Python 3.12 на Linux/macOS используются полные наборы из `requirements/`:
`runtime.txt` — бот; `web.txt` — runtime + Mini App; `dev.txt` — runtime + web + инструменты.
`build.txt` фиксирует setuptools, wheel и их зависимости. Все внешние пакеты имеют точные
версии и SHA-256; платформенные зависимости выбираются по markers. Диапазоны и состав
прямых зависимостей остаются в `pyproject.toml`. Первый lock сохраняет версии подготовленной
dev-среды; это не обновление зависимостей.

## Локальная и облачная среда

```bash
python3.12 -m venv .venv
source .venv/bin/activate
bash scripts/install-python.sh dev
# Для отдельных чистых окружений: тот же скрипт с runtime или web.
```

Скрипт принимает только готовые wheels внешних пакетов (без незафиксированных build-зависимостей
для сторонних sdist), проверяет хеши, устанавливает полный набор без повторного разрешения зависимостей,
собирает локальный проект без изолированной загрузки build backend и вызывает `pip check`.
Переключать наборы лучше в новом venv: pip не удаляет пакеты предыдущего набора.
Docker использует те же файлы, но устанавливает проект обычным wheel, без editable.
Python-база образа и системные apt-пакеты этим lock не фиксируются.

В облаке сохраняйте штатные proxy/CA и TLS-проверку. В setup-команде после создания venv
используйте скрипт выше вместо `pip install -e '.[dev,web]'`. Не сбрасывайте checkout и
не перезаписывайте lockfiles при старте. PostgreSQL 16 — только локальный синтетический:
служебная база `pullup` и отдельная тестовая `pullup_test`.

```bash
export BOT_TOKEN=ci-test-token
export TEST_DATABASE_URL=postgresql+asyncpg://pullup:pullup@127.0.0.1:5432/pullup_test
export DATABASE_URL="$TEST_DATABASE_URL"
pytest -q
ruff check app/ tests/ scripts/
```

`tests/conftest.py` создаёт тестовую БД и применяет миграции. Production URL, реальные
токены и пользовательские данные не используются. E2E — отдельная синтетическая БД
`pullup_e2e`, миграции и `scripts/e2e_seed_all.sh`, как в `.github/workflows/e2e.yml`.

## Изменение зависимостей

Генератор — `uv==0.13.4` (не нужен для обычной установки):

```bash
python -m pip install uv==0.13.4
bash scripts/lock-python.sh
```

Генерация универсальная, с markers и хешами, сохраняет существующие pins как constraints.
Для намеренного обновления удалите нужные pins из всех затронутых lockfiles, измените
диапазоны в `pyproject.toml` при необходимости и перегенерируйте все наборы. Build inputs —
`requirements/build.in`. Просмотрите diff версий и пройдите полные gates.
CI проверяет повторную генерацию, две чистые установки каждого набора и сборку backend
на Linux/macOS, затем обычные ruff, полный PostgreSQL pytest, frontend и E2E.

В управляемой среде для Docker можно передать CA без сохранения в слои:

```bash
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt -t pullup-bot .
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt -f Dockerfile.web -t pullup-web .
```

Без дополнительного CA secret необязателен; проверка TLS остаётся включённой.
