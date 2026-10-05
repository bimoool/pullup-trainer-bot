# REACHABILITY — B-fresh-catalog slice (✅ works / ❌ F-id / ⛔ BLOCKED BY / ? untested)

Legend F-ids are `F-B-fresh-catalog-NN` (written `F-NN`).

| Node | Status |
|---|---|
| Open app as new user → UI onboarding → Home | ✅ |
| Home → program card → Program Detail | ✅ (raw slug `PULL_UPS`/`pull_ups` shown: ❌ F-05 cosmetic) |
| Program Detail → «Добавить в план» → «В плане» + reload persistence | ✅ |
| Planы (empty) → «Выбрать курс на Главной» → Home | ✅ |
| Планы current week ≥1 actionable row after adding program (week 1) | ✅ (1 pool row «Подтягивания 0/3» «Начать») |
| Планы week 2+ of a program plan has rows | ❌ F-08 (empty, «На эту неделю пока ничего не запланировано») |
| Планы → Начать → pre-session → Live | ✅ |
| Live: set entry, rest skip, block switch, finish, RPE/note, summary | ✅ (strength block gets 1 set not 4: ❌ F-02; summary lacks exercise names: ❌ F-04) |
| Reload mid-Live restores phase/timer | ✅ |
| Offline set submit → reconnect → batch synced | ✅ |
| Double-tap «Сохранить и завершить» → one /complete | ✅ |
| Browser back during Live | ? UNTESTED (app uses Telegram BackButton; harness has no history) |
| Telegram BackButton during Live | ? UNTESTED |
| Журнал shows completed session (plan / free) + new context | ✅ |
| Аналитика reflects session | ✅ (raw slugs ❌ F-05; minutes 0 for custom ❌ F-06) |
| Home → «Создать тренировку» → name → editor | ✅ |
| Editor → add exercise → library list | ✅ (list shows internal «Факультатив — …» only + Планка/Отжимания: ❌ F-11) |
| Search absent exercise → «Создать своё» → protocol → add → save → reload | ✅ |
| Workout detail → Начать (≥1 exercise) → Live → complete → Журнал → Аналитика | ✅ (J3 free path) |
| Workout detail with 0 exercises → Начать | ❌ F-07 (disabled, no explanation; «Изменить» path exists) |
| Add empty workout to plan | ❌ F-07 (422 «У выбранной тренировки нет упражнений» after submit) |
| Add workout/exercise to plan when user has NO plan yet | ❌ F-01 (item stored with plan_week_id NULL, invisible, un-removable) |
| Add workout to plan when plan exists → current week day → reload | ✅ |
| Start from plan row → complete → counter 1/1, «Ещё раз» | ✅ |
| Move item to other week/day | ✅ |
| Free pool row / copy week (manual items) / prev-next week | ✅ (›on last week silently creates empty weeks: ❌ F-09) |
| Remove manual item (confirm) | ✅ |
| Remove program («История сохранится») → history intact | ✅ |
| Completed-plans tab lists removed program | ✅ |
| Re-add program → progress | ✅ week re-created, counter 0/3 (history counter not carried: F-12, P3) |
| Program catalogue size > 1 | ❌ F-03 (only one program) |
| Collection row on Home | ❌ F-13 (published collection has 0 items → not shown) |
| Program-specific baseline-based start target | ❌ F-14? (baseline 8 → target 10×3) |
| Dark theme empty states | ? UNTESTED validly (mock without themeParams) |
