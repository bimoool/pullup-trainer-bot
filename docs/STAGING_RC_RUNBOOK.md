# Staging runbook: release candidate #322 + #323

Только подготовка. **Ни одна команда отсюда не выполнялась** — деплой и запись на staging делает владелец после
независимого CLOSED по #322 и полного общего gate. Продуктовых изменений в кандидате нет: это merge двух линий
поверх BASE.

| | SHA |
|---|---|
| BASE | `608015948ef94729e73cc55e9261b912b3e039d3` |
| #322 (live-engine retry / Summary) | `e3c05f74bb09f01d4a3f83ecf698cf38f5104439` |
| #323 (ui-clarity) | `2eeff57db1f2a39db19ea91744df5ef170fe96f9` |
| Кандидат (merge, код) | `8a61187` — полный SHA: `git rev-parse 8a61187` в ветке кандидата |
| Кандидат (tip ветки) | SHA tip'а = то, что в checkpoint; поверх merge только этот документ (docs-only) |

Ветка кандидата: `claude/vigilant-clarke-xis1u1`. Деплоить **ровно tip этой ветки**; перед деплоем сверить
`git ls-remote origin refs/heads/claude/vigilant-clarke-xis1u1` с SHA из checkpoint. Любой другой SHA — стоп.

## 0. Что меняется относительно staging

* BASE опережает `integration/domain-v2` на 21 коммит, среди них **две миграции** (одна линейная голова,
  `alembic heads` = `b5d8e1f3a6c9`):
  * `e3b9c5d7a2f1` — course prescription: backfill `block_b.work_sets`, статус `awaiting_assessment`, provenance (#305);
  * `b5d8e1f3a6c9` — V5.6: подтверждения техники/отдыха по блокам сессии (#305).
* #322 и #323 сами **миграций и схемы не добавляют**. Серверный код #323: `app/domain/program_schedule.py`
  (`v5_main_schedule_row`) и `get_program_schedule` в `app/web/routes_v2.py` (карточка каталога V5.6 = 2 основных
  занятия в неделю). #322 — только фронтенд, доки и e2e.
* `e3b9c5d7a2f1` **меняет данные**: расширяет `program_inclusions.status` до 32 символов, добавляет
  `prescription_provenance` и `UPDATE`-ом дописывает `progression_state.block_b.work_sets` там, где оно пусто.
  `b5d8e1f3a6c9` — две nullable-колонки в `session_blocks`. Их `downgrade()` существует, но не возвращает backfill
  `work_sets` и переводит `awaiting_assessment` → `active` (см. §5).

## 1. До деплоя (read-only)

1. Зафиксировать текущее состояние staging: какой ref/SHA сейчас запущен и `alembic current`:
   ```bash
   docker compose -p pullup-staging exec app alembic current
   ```
   Записать значение — оно нужно для отката (§5). Если `current` уже `b5d8e1f3a6c9`, миграции в этом деплое нет.
2. Снимок БД (обязательно, миграции необратимо меняют данные backfill'ом):
   ```bash
   docker compose -p pullup-staging exec db pg_dump -U <DB_USER> -Fc <DB_NAME> > staging-before-rc.dump
   ```
3. BEFORE-снимки «старых» пользователей (только чтение; telegram-id'ы подставить):
   ```bash
   docker compose -p pullup-staging exec app python scripts/qa_state_snapshot.py --telegram-id <OWNER_TG_ID> > before-owner.json
   docker compose -p pullup-staging exec app python scripts/qa_state_snapshot.py --telegram-id <OLD_USER_TG_ID> > before-old.json
   ```
   «Старые» = (а) владелец с активной инклюзией, созданной до V5.6 (снимок без `block_b`-прескрипции);
   (б) пользователь с историей в `workouts`/`blocks` (legacy), без записей в v2-журнале;
   (в) пользователь с незавершённой live-сессией (черновик в очереди клиента).
4. Проверить, что кандидат прошёл общий gate (Playwright и pytest целиком) на этом SHA — см. `docs/STAGING_RC_GATE.md`
   (команды и изолированная БД; один прогон за раз).

## 2. Деплой (команда для владельца — не выполнять здесь)

GitHub → Actions → **Deploy Staging** → `ref` = `claude/vigilant-clarke-xis1u1` (workflow
`.github/workflows/deploy-staging.yml`, на сервере `./deploy-staging.sh <ref>`). Продовый workflow `deploy.yml` не трогать.

Образ не содержит `.git` (см. CLAUDE.md), поэтому SHA после деплоя проверять по логу workflow / по клону на VPS,
а не внутри контейнера. Ожидается SHA tip'а ветки кандидата.

## 3. Миграция и convergence (порядок важен)

Все команды из каталога staging-compose проекта (`-p pullup-staging`), не затрагивая `reeltrack-*`.

1. Миграция (если её не делает `deploy-staging.sh` — проверить по логу деплоя и `alembic current`):
   ```bash
   docker compose -p pullup-staging exec app alembic current        # ожидается b5d8e1f3a6c9
   docker compose -p pullup-staging exec app alembic heads          # одна голова
   ```
2. Convergence «старых» инклюзий (#301) — **до** того, как этот аккаунт откроет Планы на новом билде
   (рантайм лечит сам при первом `GET /plan`, и тогда dry-run скажет «nothing to do»):
   ```bash
   docker compose -p pullup-staging exec app python scripts/repair_plan_convergence.py --telegram-id <OWNER_TG_ID> > dry-run.json
   # проверить критерии из docs/STAGING_CONVERGENCE_RUNBOOK.md (result, guard_violations == [], snapshot_repairs)
   docker compose -p pullup-staging exec app python scripts/repair_plan_convergence.py --telegram-id <OWNER_TG_ID> --apply
   docker compose -p pullup-staging exec app python scripts/repair_plan_convergence.py --telegram-id <OWNER_TG_ID> --apply   # "nothing to do"
   ```
3. Сведение legacy-истории (если `a7e2c5b9d1f4` ещё не сведена на этом staging — см. `docs/deploy.md`): dry-run, затем
   `--apply`, повторный apply = 0 изменений.
   ```bash
   docker compose -p pullup-staging exec app python scripts/backfill_multi_program.py --converge-history
   docker compose -p pullup-staging exec app python scripts/backfill_multi_program.py --converge-history --apply
   ```
4. Любой `guard_violations`, exit code 4 или ненулевой счётчик на повторном apply — **стоп, откат (§5)**.

## 4. Проверка после деплоя

### 4.1 Старые пользователи (AFTER, read-only)

```bash
docker compose -p pullup-staging exec app python scripts/qa_state_snapshot.py --telegram-id <OWNER_TG_ID> > after-owner.json
docker compose -p pullup-staging exec app python scripts/qa_state_snapshot.py --telegram-id <OLD_USER_TG_ID> > after-old.json
```
Сравнить `before-*.json` и `after-*.json`:
- `diagnoses` пуст (или не хуже, чем было);
- `started_at` инклюзии, `progression_state`, `initial_progression_state` не изменились;
- число завершённых сессий и записей журнала не уменьшилось; completed-карточка у каждой сессии одна;
- старая инклюзия (до V5.6) не получила ни «2 основных в неделю», ни новых `ProgramItem` — #323 меняет только
  **новые** инклюзии (§1 в `v5_main_schedule_row`); у старой каталожная карточка прежняя.
- у пользователя с legacy-историей Журнал/Профиль/Аналитика показывают те же числа, что до деплоя.

### 4.2 Серверные smoke-проверки (авторизованный запрос не нужен — только health)

```bash
curl -sf https://staging.app.bimoool.com/health
docker compose -p pullup-staging logs --since 10m app | grep -iE "error|traceback|unhandled" || echo "clean"
```

### 4.3 Telegram + iPhone (staging-бот, реальный iPhone; прод не открывать)

Базовый чек-лист — `docs/IPHONE_QA_CHECKLIST.md`. Для кандидата дополнительно:

**#323 (ui-clarity)**
- [ ] Онбординг: после замера сразу видно объяснение помощи/веса (`describeBaselineQualification`), подписи полей
      видны и переносятся, не обрезаются; клавиатура не закрывает поле и кнопку.
- [ ] Главная/Поиск: категории показаны человеческими подписями (не слаги вроде `e2e_sweep`); чип категории в поиске.
- [ ] Каталог курса «Подтягивания»: карточка V5.6 = «Основные тренировки · 2 в неделю».
- [ ] Экран входов курса: пояснения про резину/вес, ввод резины целиком; ничего не подставляется молча.
- [ ] Журнал: имена блоков («Объём A», «Сила A (5×5)») в карточке сессии, светлая и тёмная темы.
- [ ] Просроченный платный курс — гейт; просроченные бесплатные подтягивания — доступны (`expired-free-pullups`).

**#322 (live-engine)**
- [ ] Старт V5.6-тренировки → Live → отыграть подходы → CONFIRM → «Сохранить» → Summary показывает **реальный**
      итог (прогрессия учтена / следующая роль), без ложного «Тренировка сохранена.» вместо него.
- [ ] «Завершить досрочно» → Summary «Прогрессия не пересчитана — сессия завершена досрочно.»; в журнале ровно одна запись.
- [ ] Обрыв сети на завершении: включить авиарежим на финальном подходе → выключить. Нет дублей в журнале, Summary
      нейтральный («Тренировка сохранена.»), без «прогрессия учтена». Очередь переотправляется сама, без ручного «Повторить».
- [ ] Выход с экрана Live во время отправки: нет повторных отправок, нет ошибок в консоли.

**Платформа** (то, что нельзя проверить автоматически): safe area, Back-кнопка, closing confirmation, wake lock,
работа в Telegram Desktop/Android если доступно.

Результат фиксировать в таблице из `docs/IPHONE_QA_CHECKLIST.md` (PASS/FAIL/BLOCKED).

## 5. Rollback

Критерии: падение миграции, `guard_violations`/exit 4 convergence, расхождение AFTER vs BEFORE у старого
пользователя, FAIL в §4.3 по live-engine/Journal.

1. **Код**: Actions → Deploy Staging → `ref` = SHA/ветка, записанные в §1.1 (предыдущий запущенный ref).
2. **Схема**: откат кода без отката схемы допустим — новые колонки nullable и старым кодом не читаются; `work_sets`
   старый код читает как `role_state.get("work_sets", 1)` и получает исправленное значение (комментарий в
   `downgrade()` ревизии `e3b9c5d7a2f1`). Если нужен именно откат схемы:
   ```bash
   docker compose -p pullup-staging exec app alembic downgrade <REVISION_ИЗ_§1.1>
   ```
   `downgrade()` **не** возвращает backfill `work_sets` и переводит `awaiting_assessment` → `active` (потеря
   различия статусов). Делать только после сверки обеих ревизий и репетиции на копии БД.
3. **Данные**: если convergence/backfill уже применён и данные испорчены — восстановить из `staging-before-rc.dump`
   (`pg_restore --clean`) на staging; прод не затрагивается. Convergence-скрипты ничего не удаляют (архивировать,
   не удалять — CLAUDE.md).
4. После отката повторить §4.1 (AFTER = BEFORE) и записать причину.

## 6. Что подтвердить до разрешения на деплой

- независимый CLOSED по #322 (до него общий gate не запускался);
- общий gate зелёный на SHA кандидата (`docs/STAGING_RC_GATE.md`);
- решение владельца по semantic-вопросам из checkpoint (если они есть).
