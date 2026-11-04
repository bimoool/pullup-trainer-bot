# Протокол блоков 1–2 (ревью 4b39c92), Crimpd 8.5.3, 2026-10-24. Безопасный драйвер; Logout/смена пароля/подписка не нажимались.
## Блок 1 — шестая неделя Base Endurance и Bouldering Fitness; протоколы
Перечитаны все 6 уровней (дамп доступности, y<2390; каждый файл проверен по заголовку). Base Endurance A/B/C: тестов нет ни в одной неделе; неделя 6 = Peak (A: Varied ARC Session; B: Warm Up, Style Triad, Varied ARC; C: + Continuity 10x10). Bouldering Fitness: A — без тестов (нед.6: Warm Up, Boulder Triples, 6 in 6); B — Finger Strength Test в нед.1; 7:3s 70% (нед.2–3), 75% (4–5), 80% (6); C — тест в нед.1, 7:3s 75%→80%→85% (нед.6: 85%). Протоколы открыты: Boulder Campus, Power Pulls A/B/C, Limit Power (Campus Laddering) Intermediate/Advanced/Elite, 7:3s 50/60/80%, Max Hangs, Weighted Pull Ups, Deadlift — workout-protocols.csv.
## Блок 2 — действия карты экранов («по записи»/«только открыто»), выполненные на текущем аккаунте
| Действие | До | Действие | После |
|---|---|---|---|
| Home «+» | — | открыть меню | 3 пункта + Cancel (OBS-0132) |
| Start Open Climbing Session | Home | Start Session → ✕ | живой экран; ✕ → «Discard Session» (подтверждение) → Home, записи нет |
| Log Cross-Training Workout | Analytics Cross-Training 0/0/0 | форма: Effort Easy, 15 мин, заметка → Save | запись в Logbook (Running, Workload 14, заметка); Analytics сразу после первого сохранения не читалась |
| Clone Log (Logbook → лист записи) | 1 запись | Clone → Save | 2 записи, клон с теми же заметками; Analytics Cross-Training 2 / 30 мин |
| Delete Log ×2 | 2 записи | Delete Log → подтверждение (дважды) | записей нет; Analytics показывала 1/15 до перезапуска, после холодного перезапуска 0/0/0 |
| Effort/Duration | форма | Effort Hard, Duration 20 мин, заметка → Save | Logbook: Hard, 20m, заметка; удалена |
| Карточка категории Aerobic Capacity | Home | открыть, Featured/All Workouts, «i» | вкладки и информационный диалог (OBS-0133) |
| Create Training Plan (пустой) / Starting Week | Plans | форма, выбор недели | только понедельники; все даты октября недоступны; 2 Nov — первая; Save → пустой редактор с Add Workouts/Add Skill Templates |
| Add Skill Templates | пустой план | добавить Pull-up Strength - Beginner | фазы шаблона и объёмы скопированы; Weighted Pull-up Test в неделе 6; план удалён |
| Timer Volume | max | ~50% → Save → reopen → max → Save → reopen | значения сохранялись; исходное восстановлено |
| Фильтры: Equipment×Equipment, текст+фильтры | 264 | Barbell+Dumbbell | 26; текст при Apply сбрасывается (OBS-0138) |
| Независимость упражнений между тренировками | XA=XB=2 | XA 2→4 | XB=2; обе тренировки удалены |
| Test History «…» (Profile) | история | открыть «…» | Edit Workout Log реальной записи → Cancel; история не изменена |
| Logbook календарь | — | значок «24» → календарь месяца | точки по числу тренировок дня, «+» при >2; (скриншот приватный, не сохранён) |
## Что НЕ выполнено — индивидуальные блокеры (после проверки)
- Today с назначенным занятием: Starting Week доступны только Mondays ≥ 2 Nov (rescan4_101); активировать план раньше нельзя (план владельца и ограничение «один активный»); менять план владельца запрещено. Условие: 2 Nov+ или одноразовый аккаунт. Просмотр блока Today выполнен: у In Progress плана владельца он есть, но без назначенных на день занятий (OBS-0010).
- Logout, Log In/Sign Up, Change Password, Crimpd+ Subscription: запрещены правилами задания.
- Banner Upgrade/Learn more на Plans: ведёт к покупке — запрещено.
- Первый запуск: нужен новый аккаунт.
- Time Zone и Grade System: риск реальным данным владельца.
