# STAGING FUNCTIONAL REACHABILITY — роль E (дифференциальный судья, только чтение)

Ветка `claude/wonderful-tesla-2dph8h`, HEAD `73e05cb` (код продукта = staging-деплой `1735cad`, Deploy Staging run 56,
2026-10-05; коммиты после него — только тесты/доки). Дата: 2026-10-06 (вторник, неделя 5–11 окт).
Код продукта не менялся. Методика — чек-лист `replica-diff` (шаг 3 «behaviour diff»: исходы, переходы состояний,
персистентность, пустые состояния, пути восстановления, обнаружимость — **не** скриншоты); чужая методика использована
только как чек-лист.

Связанные документы: `docs/ARCHITECTURE_RECOVERY_AUDIT.md` (роль D, далее «D §N»),
`tests/test_services/test_aged_state_convergence.py` + `scripts/qa_state_snapshot.py` (роль C),
`docs/STAGING_QA_HARNESS.md` + `webapp-frontend/e2e-staging/specs/*` (роль B), прошлые утверждения —
`docs/FUNCTIONAL_AUDIT_WAVE_1.md`, `docs/FUNCTIONAL_REACHABILITY.md`.

## 0. Легенда честности

| Метка | Что значит | Источник |
|---|---|---|
| **OBSERVED-STAGING** | Видел человек на реальном staging, реальном устройстве | только наблюдение владельца (iPhone, Telegram) |
| **REPRODUCED-LOCAL** | Воспроизведено локально настоящими путями кода (HTTP-роуты/сервисы, реальный Postgres, сдвиг часов) | матрица роли C; локальные прогоны журналов роли B в Chromium против локального бэкенда; Wave 1 (локально) |
| **CODE-READ** | Выведено чтением кода (`file:line`), не исполнялось | роль E (этот документ), роль D |
| **predicted-from-code** | Ожидаемый исход на staging по коду + знанию, что задеплоено; **на staging не запускалось** | роль E |
| **UNKNOWN** | Нет данных | — |

**Статус верификации на настоящем staging:** единственный факт = наблюдение владельца на `1735cad`:
«Текущий план «Подтягивания» / Неделя 4 · 5 окт – 11 окт / Текущая неделя · 0 из 0 / «На эту неделю пока ничего не
запланировано.»», начать тренировку курса нельзя. Staging-харнесс роли B **на staging не запускался** (egress контейнера
к staging закрыт; workflow `.github/workflows/staging-qa.yml` должен сначала попасть в default-ветку). Всё остальное в
колонках «staging» ниже — REPRODUCED-LOCAL или предсказание, не наблюдение.

**Crimpd:** референсная лаборатория (`~/android-ref-lab`) недоступна ⇒ колонка Crimpd = **UNKNOWN (lab unavailable)**
во всех строках. Отдельно, где полезно, приводится **repo-doc claim, unverified** — что утверждают наши собственные
документы (`.claude/skills/crimpd-reference/SKILL.md`, `docs/CRIMPD_*`); это не референсная истина.

---

## 1. Дифференциальная таблица

Колонки: **Fresh staging** — новый пользователь после деплоя 2026-10-05 (миграция `a4c8e1f7b2d9` кладёт каталог,
`ProgramItem`, библиотеку, системные тренировки). **Aged staging** — пользователь, чьё состояние создано старым кодом
(бэкфилл 19.09 до checkpoint 1.1, снимок инклюзии без `program_items`; либо снимок с `program_items: []`), = владелец.

| # | Intent | Crimpd | Fresh staging | Aged staging (legacy snapshot) | Divergence | Root cause |
|---|---|---|---|---|---|---|
| 1 | Найти программу/план | UNKNOWN (lab unavailable). repo-doc claim, unverified: Home = каталог по категориям, Training Plans = In Progress/Upcoming/Completed (`crimpd-reference/SKILL.md:28-29`) | ✅ predicted-from-code: Главная показывает «Подтягивания» (каталог из миграции `a4c8e1f7b2d9`); REPRODUCED-LOCAL (роль B S-FRESH-01, Wave1 fix-wave1 `fresh-install-content`) | ✅ OBSERVED-STAGING: курс виден в «Планы → Текущий план» | нет | — |
| 2 | Программа → тренировка, которую можно начать | UNKNOWN (lab unavailable) | ✅ predicted-from-code: `POST /program-inclusions` → снимок 1.1 с `program_items` + unweeked строки → привязка к текущей неделе (`program_inclusion.py:114-140`, `plan_week.py:134-143`); REPRODUCED-LOCAL (C: H1; B: S-FRESH-01; `later-weeks.spec.ts`) | ❌ **OBSERVED-STAGING + REPRODUCED-LOCAL** (C: H2b, H3b): 0 строк, «Начать» нет | **P0**: один и тот же курс даёт тренировку свежему и тупик старому | снимок без `program_items` → `continue` (`plan_week.py:150-152`); нормализация только ручным скриптом (`backfill:607-655`); deploy зовёт только `alembic upgrade` (`deploy/deploy-run.sh:37`). D §0.3 P1/P2, §6.1, §10 P0 |
| 3 | Текущая неделя | UNKNOWN (lab unavailable) | ✅ predicted-from-code «0 из 3», «Свободный пул · Подтягивания · Начать»; REPRODUCED-LOCAL | ❌ OBSERVED-STAGING «Неделя 4 · Текущая неделя · 0 из 0»; REPRODUCED-LOCAL (H2b: недели 2–4 пусты; H3b) | **P0**; противоречит `PROJECT_SPEC.md:782` («0 из 0 остаётся только у плана БЕЗ курса») | то же; плюс UI не отличает «курс активен, строк 0 — ошибка данных» от «ручной пустой план» (`DashboardScreen.tsx:1157-1164`, D §12) |
| 4 | Будущая неделя (›) | UNKNOWN (lab unavailable) | ✅ REPRODUCED-LOCAL: строки курса «Откроется …» (`later-weeks.spec.ts:41-80`, `test_v2_plan_future_weeks.py:50`) | ❌ predicted-from-code: `_materialize_inclusions_into_week` для будущих недель идёт тем же `continue` (`plan_week.py:76-81`, `:150-152`, `ensure_plannable_week` `:187-203`) ⇒ все недели 5…+4 тоже «0 из 0». На staging UNKNOWN (not yet run) | P0 (то же следствие) | D §6.1 |
| 5 | Создать свою тренировку | UNKNOWN (lab unavailable). repo-doc claim, unverified: баннер «Create Custom Workouts» (`FUNCTIONAL_AUDIT_WAVE_1.md:230`) | ✅ REPRODUCED-LOCAL (B: S-CUSTOM-01; Wave1 B1/B4). Staging: UNKNOWN (not yet run) | ✅ predicted-from-code: не зависит от плана/инклюзии (`routes_v2.py:539`) | нет | — |
| 6 | Пикер упражнений: пусто / поиск | UNKNOWN (lab unavailable). repo-doc claim, unverified: «Create Exercise: <query>» при отсутствии совпадений (`FUNCTIONAL_AUDIT_WAVE_1.md:231`) | ✅ predicted-from-code: библиотека из миграции (8 публичных упражнений, `a4c8e1f7b2d9:75-84`) видна без ввода; REPRODUCED-LOCAL (B: S-CUSTOM-01 «system exercises visible without typing»). Staging: UNKNOWN | ✅ predicted-from-code (библиотека общая) | нет (FD-04/FD-07 закрыты миграцией — локально) | — |
| 7 | Создать своё упражнение | UNKNOWN (lab unavailable) | ✅ REPRODUCED-LOCAL («Создать своё: «X»» → протокол → сохранить → reload). Staging: UNKNOWN | ✅ predicted-from-code | нет; FD-23 (упражнение сохраняется до подтверждения) — P3 | — |
| 8 | Добавить свою тренировку в план | UNKNOWN (lab unavailable) | ✅ REPRODUCED-LOCAL (S-CUSTOM-01; `test_v2_plan_items_with_week.py:151,176`: первая строка без плана → текущая неделя, #297). Staging: UNKNOWN | ✅ predicted-from-code: `POST /plan-items` → `ensure_current_plan_week` → строка в текущей неделе (`routes_v2.py:1061-1078`); это одна из **обходных дорог владельца** (§3) | нет | — |
| 9 | Начать тренировку без плана | UNKNOWN (lab unavailable) | ✅ REPRODUCED-LOCAL (S-FREE-01: системная «Максимум подтягиваний»; S-CUSTOM-01 прямой старт). Staging: UNKNOWN | ✅ predicted-from-code: Главная → «Готовые тренировки» / своя → «Начать» (`HomeScreen.tsx:306`, `routes_v2.py:1634`) — **без продвижения прогрессии курса** (`live_session.py:845-846` `not_plan_session`) | P1 для aged: доступно, но не заменяет курс | D §3 №1 |
| 10 | Начать из плана | UNKNOWN (lab unavailable) | ✅ REPRODUCED-LOCAL | ❌ OBSERVED-STAGING для строк курса (их нет); ручная строка (#8) — predicted ✅ | **P0** | §1 #2 |
| 11 | Завершить Live | UNKNOWN (lab unavailable) | ✅ REPRODUCED-LOCAL (S-FRESH-01: 3 подхода → Complete; Wave1 LIVE PASS) | ⛔ курсом недостижимо (OBSERVED-STAGING); через #8/#9 predicted ✅. Wave1 C-existing: Live работает у бэкфилленных профилей, но их снимки — **современного** формата (см. §4) | P0 (через курс) | §1 #2 |
| 12 | Журнал после завершения | UNKNOWN (lab unavailable) | ✅ REPRODUCED-LOCAL (S-FRESH-01, S-FREE-01 с reload). Staging: UNKNOWN | predicted ✅ для v2-сессий; для legacy-истории — двойной источник (D §3 №2), FD-12/FD-16 (Wave1, локально) | P2 | D §3 №1–2 |
| 13 | Аналитика после завершения | UNKNOWN (lab unavailable). repo-doc claim, unverified: круг по типам, недельные столбики, экспорт (`crimpd-reference/SKILL.md:31`) | ✅ REPRODUCED-LOCAL (S-FRESH-01). Staging: UNKNOWN | predicted ✅ для v2; ❌ FD-13 правка/удаление legacy-тренировки не отражается (Wave1 C, локально) | P2 | D §3 №2, §4 |

Пояснения к колонке Aged:
- Две формы данных воспроизводят «0 из 0» (C, REPRODUCED-LOCAL): **H2b** — снимок без ключа `program_items` (бэкфилл
  `cd2808f`, 19.09), unweeked строки уже привязаны к неделе 1 при первом открытии; **H3b** — снимок с
  `program_items: []` (курс подключён, когда у Program не было `ProgramItem`). Не воспроизводят: H1 (свежее подключение),
  H2a (тот же бэкфилл, но приложение впервые открыто только 10-06 — строки уезжают в неделю 4), H5 (дубль Program не
  создаётся), H6a (деактивированный курс — уходит в «Завершённые», экран не совпадает). H2c — повторный прогон текущего
  бэкфилла **лечит** H2b.
- Какой из H2b/H3b у владельца — UNKNOWN до SQL D §0.4 / `scripts/qa_state_snapshot.py --telegram-id <owner>` на staging.
  Датировка (неделя 1 = 14–20.09, бэкфилл 19.09) указывает на H2b (D §0.2).

---

## 2. Деревья достижимости

Значки: ✅ достижимо · ❌ тупик · ⚠ достижимо с потерей/ценой · ? не проверено. Метка источника — в скобках.

```
START FIRST TRAINING
├── Fresh → Главная → «Подтягивания» → «Добавить в план» → Планы → «Начать» → Live
│       ✅ (REPRODUCED-LOCAL: C H1, B S-FRESH-01, later-weeks/j1-course-end-to-end) · staging: predicted ✅, not yet run
├── Aged (legacy snapshot, H2b) → Планы → Текущий план «Подтягивания» → Текущая неделя
│       ❌ «0 из 0», «Начать» нет (OBSERVED-STAGING + REPRODUCED-LOCAL)
├── Aged (snapshot program_items=[], H3b) → то же
│       ❌ (REPRODUCED-LOCAL; на staging — UNKNOWN, есть ли такие инклюзии)
├── Own Workout → «Начать» (без плана)
│       ✅ fresh REPRODUCED-LOCAL (S-CUSTOM-01) · aged predicted ✅ (CODE-READ) · без прогрессии курса
├── System Workout (Главная → «Готовые тренировки» → «Максимум подтягиваний») → «Начать»
│       ✅ fresh REPRODUCED-LOCAL (S-FREE-01) · aged predicted ✅ · без прогрессии курса
└── Own Workout → «Добавить в план» → Планы → «Начать»
        ✅ fresh REPRODUCED-LOCAL (S-CUSTOM-01) · aged predicted ✅ (строка ляжет в текущую неделю, routes_v2.py:1061-1078)

CUSTOM WORKOUT
├── Главная «Своя программа»/«Создать тренировку» → имя → редактор
│       ✅ (REPRODUCED-LOCAL)
├── Пикер без ввода → системные упражнения
│       ✅ (REPRODUCED-LOCAL после миграции a4c8e1f7b2d9; было ❌ FD-04/FD-07 до неё)
├── Поиск без совпадений → «Создать своё: «X»» → протокол → «Добавить»
│       ✅ (REPRODUCED-LOCAL) · ⚠ FD-23: упражнение сохраняется до подтверждения
├── «Сохранить» → reload → деталь
│       ✅ (REPRODUCED-LOCAL)
└── → «Начать» / → «Добавить в план» → Планы
        ✅ / ✅ (REPRODUCED-LOCAL) · staging: not yet run

JOURNAL / ANALYTICS VISIBILITY (после завершения)
├── Fresh: курс → Live → Complete → Журнал «По плану» → Аналитика +1 → reload
│       ✅ (REPRODUCED-LOCAL: S-FRESH-01, Wave1) · staging not yet run
├── Free/Own: Live → Complete → Журнал «Свободная» → Аналитика
│       ✅ (REPRODUCED-LOCAL: S-FREE-01, S-CUSTOM-01)
├── Aged: через курс
│       ⛔ недостижимо — нечего завершать (OBSERVED-STAGING)
└── Aged: legacy-история (бот) в Журнале / Аналитике
        ✅ Журнал (дедуп отпечатком) / ❌ FD-13 Аналитика не видит правок/удалений legacy (REPRODUCED-LOCAL, Wave1 C)

RECOVER FROM EMPTY WEEK (aged, курс активен, текущая неделя 0 из 0)
├── Ждать следующей недели / reload / закрыть-открыть
│       ❌ (CODE-READ: каждая новая неделя идёт тем же continue, plan_week.py:150-152; REPRODUCED-LOCAL H2b: недели 2–4)
├── › в будущую неделю
│       ❌ (predicted-from-code: те же 0 строк)
├── Курс «⋯» → «Убрать курс из плана» → Главная → «Подтягивания» → «Добавить в план» → Планы → «Начать»
│       ⚠ ДОСТИЖИМО (CODE-READ), цена — сброс прогрессии курса (см. §3)
├── «+ Добавить упражнение» (текущая неделя) → публичное «Подтягивания» → «Начать»
│       ⚠ ДОСТИЖИМО (CODE-READ), не курс: прогрессия курса не пересчитывается
├── Главная → «Готовые тренировки» / своя тренировка → «Начать»
│       ⚠ ДОСТИЖИМО (CODE-READ), не курс
├── Скрытая вкладка «Dashboard» (только ADMIN_IDS) → SessionV2Lab → legacy WorkoutScreen
│       ? (CODE-READ: App.tsx:87-89, :415, :481-482, :455-461; есть ли owner в ADMIN_IDS staging — UNKNOWN); пишет только legacy
├── Бот (legacy-тренировка вне Mini App)
│       ⚠ (CODE-READ) пишет только legacy; v2-план/прогрессия не двигаются (D §4)
└── Оператор: повторный `scripts/backfill_multi_program.py` (normalize_legacy_snapshots)
        ✅ лечит, сохраняя прогрессию (REPRODUCED-LOCAL: C H2c) — НЕ UI; побочно записывает на курс всех онбордившихся без плана
        (D §14 Q2) → решение владельца
```

---

## 3. Есть ли у владельца путь вперёд через UI сегодня? (CODE-READ)

**Да, к тренировке — есть; к продолжению курса с его прогрессией — нет.**

1. **Убрать и заново добавить курс — достижимо, но с потерей прогрессии.**
   - Удаление разрешено: «⋯» на карточке курса → «Убрать курс из плана» → «Убрать»
     (`DashboardScreen.tsx:786-801`, `:926-940` → `handleRemoveInclusion` `:393-405` → `POST
     /program-inclusions/{id}/deactivate`, `routes_v2.py:927-953`): `is_active=false`, история не удаляется, будущие
     невыполненные строки снимаются (`plan_week.py:166-177`). Курс уходит в «Завершённые» (C H6a).
   - Повторное добавление разрешено: Главная считает «В плане» только по **активным** инклюзиям
     (`HomeScreen.tsx:246-248`), поэтому кнопка «Добавить в план» вернётся. `POST /program-inclusions` создаёт **новую**
     инклюзию со **свежим снимком** из live `ProgramItem` (`program_inclusion.py:114-140`, `_build_snapshot` `:20-44`) —
     на staging `ProgramItem` есть после миграции `a4c8e1f7b2d9` (`:170-182`) — и unweeked строки, которые
     `ensure_current_plan_week` сразу привязывает к текущей неделе (`routes_v2.py:920-923`, `plan_week.py:134-143`).
     ⇒ «Начать» появится в неделе 4. Тест на этот переход есть только для **свежего** снимка
     (`tests/test_web/test_v2_plan_future_weeks.py:66`); для aged не воспроизводилось (UNKNOWN на staging).
   - **Цена:** новая `progression_state` строится из `config.base_target` (блок A 10, блок Б 3; Главная не передаёт
     `initial_target_*`, `HomeScreen.tsx:266`) — `_build_initial_progression_state` (`program_inclusion.py:46-98`).
     Перенесённые бэкфиллом цели/снаряд/серии владельца остаются в неактивной инклюзии и не переносятся. Счётчики «N из M»
     начинаются заново (FD-21). Старт курсовой строки гейтится подпиской (#300) — статус подписки владельца UNKNOWN.
     Это продуктово значимая потеря ⇒ **не рекомендовать владельцу без его решения** (CLAUDE.md п.6).
2. **Ручная строка в текущей неделе** — «+ Добавить упражнение» виден в редактируемой неделе (`DashboardScreen.tsx:1176-1186`);
   публичное «Подтягивания» есть в библиотеке (`a4c8e1f7b2d9:76`); STEP-роли «Подтягивания — объём/сила» скрыты от
   публичного пути (`routes_v2.py:1040-1043`, `programs.py:243`). Сессия завершится, попадёт в Журнал/Аналитику, но
   прогрессия курса не пересчитается (`live_session.py:845-860`).
3. **Без плана** — «Готовые тренировки» (системные «Максимум подтягиваний», «W-лесенка», «3 минуты подтягиваний»,
   `a4c8e1f7b2d9:86-110`) или своя тренировка → «Начать». Курс не двигается (`not_plan_session`).
4. **Админ-вкладка / бот** — пишут только legacy; v2-курс не лечат.
5. **Без потерь лечит только оператор** (повторный бэкфилл, C H2c), т.е. не UI.

Обнаружимость: на экране нет ни объяснения, ни CTA, связывающего «0 из 0» с курсом; единственная подсказка —
«+ Добавить упражнение», ведущая к пути 2 (D §12 «фронт полагается на материализацию»).

---

## 4. Аудит тестов: какие тесты «доказали», что это работает, и почему они прошли

### 4.1 Инцидент владельца (aged legacy snapshot → текущая неделя 0 из 0)

| Тест / утверждение | file:line | Что утверждал | Почему прошёл |
|---|---|---|---|
| `test_rollover_creates_new_items_in_new_week_keeps_old_week_intact` | `tests/test_services/test_plan_week_service.py:152` | rollover неделя 1 → 2 даёт строки | хелпер кладёт `program_items` в снимок (`:63-82`, вызов `:154` с `program_items=`) — **снимок всегда содержит program_items** |
| `test_unweeked_existing_plan_items_get_attached_not_duplicated` | `test_plan_week_service.py:125-144` | «имитация мигрированного до checkpoint 1» работает | единственный тест с legacy-формой снимка (`:127` без `program_items`), но проверяет **только неделю 1** (ветка `attach_unweeked`); **нет прошедших недель** |
| блок #301 (`test_plannable_future_weeks_get_course_rows_idempotently`, `test_existing_empty_future_week_is_filled_…`, `test_rollover_after_prematerialisation_…`) | `test_plan_week_service.py:434`, `:457`, `:476` | будущие/следующие недели не пусты | снимок с `program_items` (`:437`, `:460`, `:479`) |
| `test_future_week_created_by_stepper_has_course_rows_and_get_is_idempotent`, `test_readd_after_removal_…` | `tests/test_web/test_v2_plan_future_weeks.py:50`, `:66` | #301 закрыт на уровне API | курс подключается `POST /program-inclusions` **в тот же день** (`:42-46`) — свежий снимок, **нет истории миграций**, **нет прошедших недель** |
| `test_legacy_snapshot_without_program_items_gets_normalized` | `tests/test_scripts/test_backfill_multi_program.py:414-461` | legacy-снимок «обработан» | закрепляет **нормализацию как ручной шаг оператора** (`backfill_all`), а не рантайм-инвариант; GET /plan после этого не вызывается, PlanWeek/PlanItem = `[]` (`:450-451`) |
| e2e `later-weeks.spec.ts` (журнал-регрессия #301) | `webapp-frontend/e2e/scenarios/fix-wave1/later-weeks.spec.ts:41-80` | «недели 2 и 3 не пустые», «0 из 0» запрещено | **свежий пользователь**, курс добавлен через UI сейчас, недели 2/3 — **будущие по степперу, а не прошедшие**; часы не двигаются; чистая локальная БД `alembic upgrade head` (`:3-8`) |
| e2e `full-sweep.spec.ts` «Будущая неделя (#301)» | `webapp-frontend/e2e/scenarios/parity/full-sweep.spec.ts:763-772` | будущая неделя показывает строки курса | сид `seed_sweep_populated` (`scripts/e2e_seed.py:1406`) подключает курс `ProgramInclusionService` **сегодня** (`:1453-1455`) поверх плана с **заранее созданными** неделями/PlanItem (`seed_plan_week_stepper`, `:612-643`, `TrainingPlan(created_at=now-14d)`) — **pre-created week + pre-created PlanItem**, снимок свежий |
| e2e Планы (`plans-plan-week`, `plans-start-session`, …) | `scripts/e2e_seed.py:404-452` (`seed_plan_week_ready`) | текущая неделя с «Начать» | `create_inclusion` **сегодня**; первая неделя через `attach_unweeked`; **нет прошедших недель** |
| Wave 1: «Current week has an actionable row … PASS», «Week rollover for a returning user … PASS» | `docs/FUNCTIONAL_AUDIT_WAVE_1.md:102`, `:153`; `docs/FUNCTIONAL_REACHABILITY.md:19`, `:49` | «existing» профили (бэкфилл) видят «0 из 3» и переход недели | профили C созданы **текущим** бэкфиллом (`docs/audit/wave1/C-existing/PROFILES.md:6`), чей `seed_catalog` уже пишет `program_items` (`scripts/backfill_multi_program.py:281`); переход недели — **инъекция S0** (`PROFILES.md:43-48`, «upstream S0 injected»); **local DB only**. Историческая форма данных 19.09 не воспроизводилась ни разу |
| `FUNCTIONAL_AUDIT_WAVE_1.md:4` «Not reproduced (owner symptoms) … plan with zero workouts» | `docs/audit/wave1/C-existing/FINDINGS.md:4` | симптом владельца не воспроизводится | тот же современный бэкфилл; вывод «не воспроизводится» сделан на данных, которые не могут его воспроизвести |

**Итог:** ни один тест/журнал не исполнял `_materialize_inclusions_into_week` на ветке `program_items_snapshot` falsy в
неделе ≥ 2 (`plan_week.py:150-152`). Все «PASS» — один из: свежий пользователь; снимок всегда с `program_items`;
нет прошедших недель (будущие по степперу ≠ прошедшие по календарю); заранее созданные недели/PlanItem из `e2e_seed.py`;
нормализация как ручной операторский шаг; локальная БД без истории миграций/бэкфиллов staging. Это ровно D §10 P1
«тестовые данные создаются в обход продуктовых путей» и D §15.

### 4.2 Прочие staging-risk расхождения

| Расхождение | Тест, который «покрывает» | Почему не ловит |
|---|---|---|
| H3b `program_items: []` | — (нет) | `_build_snapshot` в тестах всегда видит ProgramItem; Program без items создаёт только `test_non_recurring_program_is_not_materialized` (`test_plan_week_service.py:305`) — и там проверяется SINGLE_LESSON |
| Re-add как обход (сброс прогрессии) | `test_v2_plan_future_weeks.py:66` | проверяет отсутствие дублей/призраков строк, не сохранность `progression_state` |
| Застывшая legacy-прогрессия (D §6.5) | Wave1 C (FD-09/FD-10) | замечено как P2-расхождение целей, не как отсутствие синхронизации |
| `not_migrated` у онбордившихся после бэкфилла (D §6.4) | — | сиды создают план напрямую |
| Две активные инклюзии (D §6.8) | клиентская защита `HomeScreen.tsx:262-264` | нет серверного теста двойного POST |
| UTC vs локальная неделя (D §7) | тесты домена с чистыми `date` | материализация бэкфилла с UTC `today` не тестируется против рантайма |

### 4.3 Редизайн: регрессия на границе пользовательского пути

1. **Staging, aged identities (роль B, `S-OWNER-01`)** — `webapp-frontend/e2e-staging/specs/01-s-owner-01.spec.ts:34-35`
   гоняет `qa_aged_active` **и** `qa_aged_legacy_snapshot` (`docs/STAGING_QA_HARNESS.md:48-49,62`): только UI, запрет
   «0 из 0» + «На эту неделю пока ничего не запланировано.» при активном курсе, reload + новый запуск, дамп
   `/api/v2/plan`. Ожидание до починки — **красный** `qa_aged_legacy_snapshot` (локально подтверждено ролью B). Добавить
   identity формы H3b (`program_items: []`) и, после SQL D §0.4, — точную форму данных владельца (бэкфилл `cd2808f`:
   строки из `snapshot["exercises"]`, `count_per_week=3`). Должен стать обязательным гейтом после Deploy Staging.
2. **Локально — strict-xfail сходимости (роль C)**: `tests/test_services/test_aged_state_convergence.py` (H2b, H3b — xfail
   strict; H1, H2c — зелёные контроли). Строятся реальными путями (`POST /program-inclusions`, `GET /plan` со сдвигом
   `_utcnow`), руками меняется только форма снимка. При починке маркер снимается; доказательство — откат фикса
   возвращает xfail (CLAUDE.md «тест доказывается откатом»).
3. **Инвариант-чекер (D T4)**: «каждая активная RECURRING-инклюзия ⇒ в текущей неделе ≥ 1 её PlanItem **или** неделя
   явно REST», + «у активной RECURRING-инклюзии непустой `snapshot.program_items`». Исполнять: (a) в pytest после каждого
   теста `tests/test_web/test_v2_plan*`/`test_services/test_plan_week*` (fixture-хук по всем планам тестовой БД);
   (b) в e2e после каждого журнала по e2e-БД; (c) read-only на staging после деплоя (`scripts/qa_state_snapshot.py`
   уже печатает `snapshot_has_program_items` и счётчики по неделям — нужен агрегат по всем пользователям, D §0.4 запрос 4).
4. **Запрет «удобных» сидов для путей материализации**: журналы Планов должны начинать с состояния, созданного продуктом
   (UI/API) в прошлом, со сдвигом часов — а не с `TrainingPlan(created_at=now-14d)` + ручных `PlanItem`.

---

## 5. Почему локальная волна фиксов прошла, а iPhone — нет

Волна #301 чинила **свежую** траекторию и проверяла её **свежими** данными: каждый тест и журнал создавал инклюзию
сегодняшним кодом (`ProgramInclusionService`/`POST /program-inclusions`, снимок с `program_items`), а «следующие недели»
получал степпером вперёд, не прожив их по календарю; «существующие» профили Wave 1 были сконвертированы **текущим**
бэкфиллом, который сам пишет `program_items`, а переход недели у них был инъекцией. У владельца же инклюзия создана
бэкфиллом 19.09 до checkpoint 1.1 — снимок без `program_items`; неделя 1 съела unweeked-строки, и каждая следующая неделя
попадает в тихий `continue` (`plan_week.py:150-152`), а единственное лечение (`normalize_legacy_snapshots`) живёт в ручном
операторском скрипте, который деплой (`deploy/deploy-run.sh:37`, только `alembic upgrade head`) не вызывает. Тестовая
матрица не содержала ни этой формы данных, ни прошедших недель, ни инварианта «активный курс ⇒ строки в текущей
неделе», поэтому всё было зелёным, пока реальные данные staging шли по ветке, которую ни один тест не исполнял.

---

## 6. Список расхождений по приоритету

| ID | Приор. | Расхождение | Статус доказательства | Корень (D) |
|---|---|---|---|---|
| DV-01 | **P0** | Aged (legacy snapshot без `program_items`): текущая и все последующие недели «0 из 0», курс не стартуется | OBSERVED-STAGING + REPRODUCED-LOCAL (H2b) | D §0.3 P1, §6.1, §10 P0 «сходимость не инвариант» |
| DV-02 | **P0** | Лечение есть только как ручной операторский скрипт; деплой не сводит данные; миграции не нормализуют снимки | CODE-READ (`deploy-run.sh:37`, `backfill:607-655`), REPRODUCED-LOCAL (H2c лечит) | D §0.3 P2, §9, §10 P0, T1/T6 |
| DV-03 | **P0** | Нет проверки инварианта (код/тесты/мониторинг); баг виден только владельцу | CODE-READ + §4.1 | D §10 P0 №2, T3/T4 |
| DV-04 | **P1** | Снимок `program_items: []` (H3b) — тот же тупик; рантайм не лечит, ручной нормализатор лечит (пустой список falsy, `backfill:624` перезапишет, если `program_id` совпадает с сидом `:620`) | REPRODUCED-LOCAL; распространённость на staging UNKNOWN | D §0.3 P3, §6.3 |
| DV-05 | **P1** | Единственный UI-обход для курса (убрать → добавить) сбрасывает прогрессию на `base_target` и счётчики | CODE-READ | D §3 №1, §6.5, §6.13 |
| DV-06 | **P1** | UI не отличает «курс активен, 0 строк» (ошибка данных) от пустого ручного плана; нет объяснения/CTA | CODE-READ (`DashboardScreen.tsx:1157-1164`) | D §12 «фронт полагается на материализацию», T3 |
| DV-07 | **P1** | Прогрессия aged-пользователя заморожена на 19.09; бот-тренировки её не двигают | CODE-READ; Wave1 FD-09/FD-10 (локально) | D §3 №1, §6.5, §10 P1 (legacy/v2) |
| DV-08 | **P1** | Тестовые сиды создают состояние в обход продукта ⇒ e2e зелёный, staging сломан | §4.1 | D §10 P1, §15 |
| DV-09 | **P1** | Онбордившийся после бэкфилла legacy-пользователь — `not_migrated` до ручного «Добавить» | CODE-READ; на staging UNKNOWN | D §6.4 |
| DV-10 | P2 | Две активные инклюзии одного курса → `multiple_active_inclusions` | CODE-READ | D §6.8, T7 |
| DV-11 | P2 | 3 базы времени (UTC/tz/устройство): бэкфилл материализует «прошлую» неделю у UTC+N в понедельник ночью | CODE-READ | D §6.10–11, §7 |
| DV-12 | P2 | Аналитика не отражает правку/удаление legacy-тренировок (FD-13); `admin_reset` не сбрасывает v2 | REPRODUCED-LOCAL (Wave1) / CODE-READ | D §3 №2, §4, §6.6 |
| DV-13 | P2 | Fresh-путь на staging (S-FRESH/CUSTOM/FREE) не исполнялся — «predicted ✅» не равно наблюдению | UNKNOWN on staging | — (процесс: harness роли B не запущен) |

Открытые вопросы владельцу (не решались здесь): D §14 Q1 (T1 — рантайм-заполнение отсутствующего `program_items`
противоречит записанному решению `plan_week.py:112-121`), Q2 (прогнать нормализацию на staging сейчас после SQL §0.4),
и новое: **допустимо ли советовать «убрать и добавить курс» как временный обход при сбросе прогрессии (DV-05)?**
