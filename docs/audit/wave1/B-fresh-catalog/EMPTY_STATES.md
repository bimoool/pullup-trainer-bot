# EMPTY_STATES — B-fresh-catalog (install with catalogue: 1 program, 2 general exercises, 0 system workouts)

HARNESS.md does not enumerate E1–E12; I defined them as the empty/zero states reachable by a new user. User 7200003 (onboarded, nothing else).
Screenshots in `artifacts/` (file name prefix `empty-NN-…`, `j2-…`, `j3-…`).

| # | SCREEN | MESSAGE (verbatim) | CTA | CTA resolves it? | Screenshot |
|---|---|---|---|---|---|
| E1 | Планы → Сейчас, no plan | «Курсов в плане нет. Добавьте курс на Главной.» | «Выбрать курс на Главной» | YES here (catalogue has «Подтягивания»); on a clean install (no programs) it would dead-end (B-fresh-clean's scope) | empty-02-E-plans.png |
| E2 | Планы, plan exists, current week has 0 rows (program removed, or manual item invisible) | «Текущая неделя · 0 из 0» / «На эту неделю пока ничего не запланировано.» | «+ Добавить упражнение» (sheet with the 6 library exercises + day) | PARTLY: works if a plan exists; if the plan was just auto-created by the first add the new item is lost (F-01) | j2-01-after-add.png, search-01-after-add.png |
| E3 | Планы → Завершённые | «Завершённых курсов пока нет. Убранные из плана курсы появятся здесь.» | none | n/a (informational) | empty-03-E-plans-completed.png |
| E4 | Планы → «Мои тренировки» / Home «Мои тренировки» (0 workouts) | Planы: «У вас пока нет своих тренировок»; Home: «Соберите свою тренировку из упражнений и протоколов.» | «Создать тренировку» | YES | empty-04-E-myworkouts.png, onb-02-reload.png |
| E5 | Workout detail, 0 exercises | «Пока без упражнений» / «В тренировке пока нет упражнений» / history «Вы ещё не выполняли эту тренировку» | «Изменить» (works); «Начать» is disabled with no explanation (F-07) | YES via «Изменить» | j3-01-empty-detail.png |
| E6 | Workout editor, 0 exercises | «Пока пусто. Добавьте первое упражнение и настройте, как его выполнять.» | «+ Добавить упражнение» | YES | j2-01-after-create.png |
| E7 | Exercise picker, no match | «Ничего не найдено» + row «Создать своё: «Австралийские подтягивания»» | «Создать своё» | YES (creates user exercise, opens protocol sheet) | j2-01-search-aus.png |
| E8 | Журнал, 0 sessions | «В этом месяце тренировок нет» | «+ Записать» (→ «Тренировку из моих» / «Другую активность») | YES (but «Тренировку из моих» with 0 workouts untested) | empty-05-E-journal.png, empty-07-E-log-activity.png |
| E9 | Аналитика, 0 sessions | «За выбранный период нет данных.» ; «Пока нет завершённых тренировок из «Мои тренировки» — показатели по упражнениям появятся после первой.» | none; page still shows 0-stat tiles and an export block | n/a | empty-06-E-analytics.png |
| E10 | Профиль, 0 trainings | «Тренировок пока не было.»; «Ещё не проходили» ×3; ГТО: «Внеси первую тренировку, чтобы узнать свой разряд ГТО.»; WSF: «Внеси тренировку блока Б на отягощении или собственном весе, чтобы узнать свой разряд WSF.» | none | n/a | empty-07-E-profile.png |
| E11 | Search/«Все ›», no results | «Найдено: 0» / «Ничего не найдено» | filter chips «Сбросить» | n/a | empty-06-E-search-none.png |
| E12 | Home, collections | No collections row at all although `collections` has 1 published row «Начни с подтягиваний» with 0 items (F-13). Home also has no «Мои тренировки» workout list until one exists | — | n/a | onb-02-reload.png |

Home «Готовы заниматься? Откройте план дня» with no plan lands on E1. Home «Своя программа» opens the same «Новая тренировка» name form as «Создать тренировку» (no program/complex builder).

Dark pass: ATTEMPTED, INVALID. My ad-hoc Telegram mock set `colorScheme=dark` without `themeParams` (the repo mock supplies them), so the result mixed light surfaces with a white title («Планы» white on light grey, `dark-02-plans-empty.png`). Not reported as a product finding; dark empty states are UNTESTED.
