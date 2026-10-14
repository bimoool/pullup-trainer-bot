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

## Результаты gate на кандидате с #325 + #326 (кодовый коммит `3f10ecff7b22da70c9b888c55a99f39e1247d965`)

Изолированный Postgres 16 (порт 54329), по одному прогону за раз, 13–14 октября 2026 (UTC 20:55 – 21:50). Состав: `ef607c0`-кандидат + #325 (`43b9248`) + #326 (`a35e1c7`) +
Dockerfile `npm ci` + guarded deploy (preflight/область/неразрешённые) + `--user-ids` у скриптов сведения. Заявленный объём изменений проверен: нестандартных (не-docs) файлов вне #325 ∪ #326 ∪ собственных нет.

| Шаг | Результат |
|---|---|
| Alembic heads | один: `b5d8e1f3a6c9` |
| Seed integrity | 14 passed |
| `ruff check app/ tests/ scripts/` | 0 замечаний |
| Backend `pytest -q` | **2689 passed, 1 failed** (12 мин 35 с) |
| Frontend build | OK |
| Frontend unit | 329/329 (было 320; +9 тестов #325) |
| Engine vectors | 34/34 |
| Полный E2E (чистая БД, `alembic upgrade head`, `e2e_seed_all.sh`, затем `npm test`) | **558 passed, 1 failed, 8 skipped** (13,3 мин; было 555/0/8, +3 теста #325) |
| Репетиция `c3f7a9e2d5b1` + старый код `4298f8b` (`rehearse.sh`) | OK, см. ниже |
| Репетиция отредактированных/удалённых копий (`edited_copy_run.sh`, старый код `4298f8b`) | OK, см. ниже |

### Два падения — оба зависят от времени суток/дня недели, не от кандидата

Прогон шёл с 23:55 по Москве (UTC+3) 13-го до 00:50 14-го — календарный день и день недели в `Europe/Moscow` (часовой пояс пользователей по умолчанию) отличаются от UTC-даты. Падения воспроизведены на **ранее принятом `ef607c0`** (код не менялся этими коммитами):

1. `tests/test_web/test_history.py::test_history_returns_newest_first_with_target_only_on_latest` — сравнивает `(now_utc − 1 день).date()` (UTC) с датой карточки в часовом поясе пользователя; между 21:00 и 24:00 UTC дата в Москве на день вперёд
   (`'2026-10-13' == '2026-10-12'`). Те же 5 из 6 тестов файла проходят; на `ef607c0` при том же времени падает так же; с зафиксированным часом `2026-10-13 12:00 UTC` (плагин `freezegun`, сам тест не менялся) — **6 passed**.
2. `webapp-frontend/e2e/scenarios/fix-wave1/first-add-to-plan.spec.ts:44` — фиксированно выбирает в «Добавить в план» день «СРЕДА»; когда сегодня (по Москве) среда, строка видна дважды (блок «Сегодня» и список недели) и `getByRole(...)` ломается в strict mode
   (`resolved to 2 elements`). 14 октября 2026 — среда. На `ef607c0` (сервер и сборка из его worktree) воспроизводится той же ошибкой. Предыдущий gate шёл во вторник (по Москве).
   Проверка при другом дне недели не выполнена: сдвигать часы сервера нечем (`freezegun` ломает ASGI-сервер, `faketime` нет). Падение не маскируется и не исправляется в этом кандидате; тест подлежит отдельной правке.

Продуктовых регрессий не найдено; остальные 2689 + 558 прошли. Эти два теста **красные по средам по Москве** (вт 21:00 UTC – ср 21:00 UTC) и красные при запуске в 21:00–24:00 UTC, пока не исправлены. CI E2E на этом SHA прогонится в окно, зависящее от времени запуска.

### Репетиция от `c3f7a9e2d5b1` со старым кодом `4298f8b` (кандидат `3f10ecf`, `docs/rehearsal/rehearse.sh old_c3b c3n`)

* `alembic upgrade head` exit 0 → `b5d8e1f3a6c9`; цепочка — 7 миграций (runbook §4).
* Сведение плана: разведка `--all` (только чтение) → `--user-ids <все с планом>`: dry-run 50 / `apply` 50 / повторный `apply` **0**, `guard_violations` 0, dry-run ничего не записал (диф снимков пуст). Число мутаций зависит от даты относительно синтетики (на прошлом прогоне 55, `session_credits_linked` теперь 0) — проверяются предикаты, не числа.
* Сведение истории: dry-run ничего не пишет; `--user-ids` apply: привязано 5, создано 3; повторный apply — только «без изменений»; блок «Не разрешено»: 0 (на этом наборе), apply1 = apply2.
* Diff «до → после» — как в `docs/STAGING_RC_REHEARSAL.md` §3/§9 (plan_items 24→43, plan_weeks 10→12, training_sessions 230→233, session_blocks 227→233, set_logs 457→484; новые таблицы `custom_plans`, `exercise_categories` 11, `session_events`, `workout_definition_versions` 10).
* Отредактированные копии (`edit`): привязано 8, создано 2 (= по одной post-migration тренировке на пользователя), **не разрешено 6** (не воскрешены), повторный apply — только «без изменений», список неразрешённых стабилен; `profile` IDENTICAL у обоих пользователей.
  Удаление всех копий (`delete-all`): создано 2, **не разрешено 8**, `profile` IDENTICAL. Результат совпадает с доказательствами #326.
* Наблюдение (не дефект репетиции): в `journal/days` легаси-тренировки теперь группируются по **локальному** дню пользователя, а в коде `4298f8b` — по UTC-дате (`routes_v2.py`, #308 A1: «день — локальный день»). Тренировки между 21:00 и 24:00 UTC у пользователей в Москве после выкатки
  переедут в Журнале на следующий день (в репетиции: 5/1 → 4/2 на 13-е/14-е при неизменной сумме 7); к этому проекту решение (A1) уже принято, но это видимое пользователю изменение для проверки на staging (runbook §7).

### CI на `29180c0` (код `3f10ecf`), проверено 22:22 UTC

ruff, security, frontend build, claude-review — success. **pytest — failure, e2e — failure.** Имена упавших тестов получить не удалось: хост с логами (`*.blob.core.windows.net`) закрыт прокси, а инструмент логов вернул только вывод сервисного контейнера Postgres
(в нём лишь ожидаемые `duplicate key` из тестов на конкурентность и `FATAL: database "pullup" does not exist` из health-проверки контейнера), check-runs без output. Прогон CI шёл в окне 21:52–22:17 UTC (вторник → среда по Москве), то есть в условиях обоих
времязависимых тестов (см. выше), поэтому красные pytest/e2e **согласуются** с ожиданием, но **не подтверждены**. Нужно открыть логи джобов в Actions и убедиться, что упали только `test_history…newest_first…` и `first-add-to-plan.spec.ts`; пока этого нет, CI считать красным без классификации.

## Исправления тестов по логам CI и повторный gate (код `86e50ec`)

Логи CI на `29180c0` (job pytest `115559239339`, e2e `115559238556`): backend 2688 passed / 1 failed / 1 skipped; E2E 554 / 4 failed / 8 skipped. Область работы задана сообщением владельца. Продуктовый код не менялся — только тесты.

| Падение в CI | Причина | Исправление | Проверка |
|---|---|---|---|
| `test_history…newest_first…` (`'2026-10-13' == '2026-10-12'`) | ожидание строилось из `now(UTC)`; контракт #308 A1 — дата карточки в **локальном** дне пользователя (`users.timezone`, по умолчанию Москва) | фиксированные моменты + явный `users.timezone`, 5 случаев вокруг границы суток: Москва 20:59/21:00 UTC, дефолт, UTC-пользователь, Владивосток; ожидание — из контракта (`resolve_timezone`) | 10 passed; мутация «карточка берёт UTC-дату» валит 3 из 5 |
| `first-add-to-plan` (две кнопки «Начать: …») | в среду по Москве строка есть и в блоке «Сегодня» (подпись `Начать: <название>`), и в списке недели (`Начать: <название>, среда`) | кнопка недели выбирается по подписи дня (`exact`), блок «Сегодня» проверяется отдельно, когда выбранный день — сегодня; `.first()` не используется | в среду (дубль есть, блок «Сегодня» = 1) и при временной подмене на четверг (дубля нет) — passed |
| Favorites @390px light (1 карточка вместо 2) | сердечко — оптимистичный тумблер; ряд на Главной и состояние после reload читаются с сервера, а тест уходил с экрана/перезагружал страницу, не дождавшись PUT. Воспроизведено: PUT с задержкой 1,5 с → «Received: 0» после reload; чистый профиль без задержки проходит | сценарий ждёт завершённый PUT/DELETE (200) перед уходом/reload; Expected 2 не менялся | 8 из 8 Favorites; с задержкой PUT/DELETE 1,5 с — passed |
| live-engine №17, №18 (`storedEngineQueues = 0` вместо 1) | **не установлена.** Локально проходят (в т. ч. при троттлинге CPU ×6 и 4 нагружающих процессах); браузер локально тот же (Chromium 153, rev 1243, Playwright 1.63). Установлено: экран показывает «Стоп» до фиксации записи в IndexedDB (`setQueue` → `await save`), а общий помощник закрывал исходную страницу без проверки, что очередь сохранена (тест №8 такую проверку имеет). Это правдоподобно, но **для CI не доказано** | `Expected 1` не менялся. Перед закрытием исходной страницы — опрос «очередь сохранена» (5 с); новый наблюдатель различает «хранилища нет» / «записей нет» / ошибку чтения и печатает состояние в сообщении; проверка сразу после запуска со сбоем чтения (до повторов) | оба теста проходят локально; продуктовый дефект не подтверждён, очередь не менялась |

Для окончательной причины №17/№18 нужны артефакты CI: ошибка и trace **первой** попытки (в CI `retries: 1`, ретрай идёт по уже изменённому состоянию пользователя) — `playwright-report` из job e2e.

### Один общий gate после всех исправлений (`86e50ec9b3689f4f2a0540e4d68c88801b5f7848`, 14 октября 2026, ~09:05–10:00 по Москве — среда, дубль строки плана присутствует)

| Шаг | Результат |
|---|---|
| Alembic heads | один: `b5d8e1f3a6c9` |
| Seed integrity | 14 passed |
| `ruff check app/ tests/ scripts/` | 0 замечаний |
| Backend `pytest -q` | **2694 passed, 0 failed** (15 мин 28 с) |
| Frontend build / unit / vectors | OK / 329 из 329 / 34 из 34 |
| Полный E2E, чистая БД и reseed | **559 passed, 0 failed, 8 skipped** (15,7 мин) |
