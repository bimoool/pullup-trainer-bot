# E2E-тесты Mini App (Playwright)

Реальный браузерный рендер React-приложения против настоящего
`app/web/main.py` (FastAPI + Postgres), не HTTP-моки — ловит то, что
`pytest` в `tests/test_web/` не может по конструкции: "кнопка показана,
хотя не должна быть" (issue #123), необработанные ошибки в консоли
браузера и т.п. Дополняет `pytest`, не заменяет — см. issue #126.

Аутентификация Mini App — `X-Telegram-Init-Data`, подпись которой обычный
HMAC на `BOT_TOKEN` (`init_data_py`, см. `app/web/auth.py`). Реальный
Telegram не нужен: `fixtures/initData.ts` подписывает синтетический
initData тем же алгоритмом и тем же `BOT_TOKEN`, с которым поднят тестовый
сервер (сверено чтением исходника `init-data-py==0.2.7`, не только по
докстрингу `test_auth.py`).

## Первая итерация (issue #126)

Три сценария — `not_onboarded`, `first_workout` (обязательный, issue #123),
`ready`. Остальные пять из исходного issue (`too_early`/`no_access`/
`gap_retest_required`, `is_deload_a`/`is_heavy_b`) — отдельными issue после
того, как эта инфраструктура (CI/сиды/mock initData) обкатана на первых
трёх.

## Локальный запуск

```bash
# 1. Поднять тестовую БД (тот же db-сервис, что и у pytest, см. tests/conftest.py)
docker compose up -d db
docker compose port db 5432   # узнать эфемерный порт хоста

# 2. Применить миграции на отдельную БД (не dev pullup, чтобы не мешать вручную)
DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:<port>/pullup_e2e \
  alembic upgrade head

# 3. Собрать фронтенд (то же самое, что кладёт Dockerfile.web в dist/)
cd webapp-frontend && npm install && npm run build && cd ..

# 4. Поднять сервер с тестовым BOT_TOKEN (тем же, которым E2E подпишет initData)
BOT_TOKEN=e2e-test-token \
DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:<port>/pullup_e2e \
  uvicorn app.web.main:app --port 8001 &

# 5. Посеять сценарии (по одному вызову на telegram_id, см. scripts/e2e_seed.py)
BOT_TOKEN=e2e-test-token \
DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:<port>/pullup_e2e \
  python scripts/e2e_seed.py first_workout 900002
BOT_TOKEN=e2e-test-token \
DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:<port>/pullup_e2e \
  python scripts/e2e_seed.py ready 900003
# Волна 5 (issue #185) — сценарии экрана сессии (v2), см. ниже про ADMIN_IDS.
BOT_TOKEN=e2e-test-token \
DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:<port>/pullup_e2e \
  python scripts/e2e_seed.py v2_session_ready 900010
BOT_TOKEN=e2e-test-token \
DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:<port>/pullup_e2e \
  python scripts/e2e_seed.py v2_session_complex 900011
BOT_TOKEN=e2e-test-token \
DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:<port>/pullup_e2e \
  python scripts/e2e_seed.py v2_session_progression_edit 900012

# 6. Прогнать Playwright (BOT_TOKEN тот же самый — им подписывается initData)
cd webapp-frontend/e2e
npm install
npx playwright install --with-deps chromium
BOT_TOKEN=e2e-test-token npm test
```

`not_onboarded` (telegram_id `900001`) ничего не сеет — статус означает
отсутствие строки `users`, шаг 5 для него не нужен.

## Сценарии экрана сессии (волна 5, issue #185) — нужен ADMIN_IDS

Пред-экран/live/итог/журнал-правка v2 (`SessionV2Lab.tsx`) — вкладка "🧪
Dashboard" в нижнем меню, видна только `app.config.settings.is_admin`
(`App.tsx::DASHBOARD_V2_NAV_TAB`) — тот же admin-only испытательный стенд,
что и `DashboardV2Screen.tsx` с волны 4 (`.claude/skills/multi-program/
SKILL.md`: старая схема остаётся источником истины до cutover). Локальный
запуск шага 4 (`uvicorn`) для сценариев `v2_session_*` нужно поднимать с
`ADMIN_IDS=900010,900011,900012` (или шире) в окружении, иначе кнопка
"Dashboard" не появится в нижнем меню вообще и сценарии упадут на первом же
`page.getByRole("button", { name: "Dashboard" })`.

**Известное ограничение этой волны**: `.github/workflows/e2e.yml` не
обновлён этим PR — агент, готовивший волну, не имеет прав на правку
`.github/workflows/*`. Чтобы сценарии `v2_session_*` реально гонялись в CI,
нужно вручную добавить в `e2e.yml`:
  - `ADMIN_IDS: "900010,900011,900012"` в блок `env:` джобы `e2e`;
  - в шаг "Seed E2E scenarios" — три вызова `python scripts/e2e_seed.py
    v2_session_ready 900010` / `v2_session_complex 900011` /
    `v2_session_progression_edit 900012`, как в шаге 5 выше.

## Известное ограничение этого PR

`webapp-frontend/e2e/package.json` добавлен без `package-lock.json` —
npm был недоступен из песочницы Claude в сессии, где готовился этот PR
(тот же класс непостоянного ограничения сети, что уже не раз фиксировался
в `docs/mini-app.md` для `webapp-frontend/`). Первый `npm install` в CI или
локально сгенерирует лок-файл — его стоит закоммитить в этот же каталог
после первого успешного прогона, по аналогии с тем, как уже сделано для
`webapp-frontend/package-lock.json`.
