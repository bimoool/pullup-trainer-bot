# REACHABILITY — B-fresh-clean slice (pure clean install, new user)

Legend: ✅ works and persists after reload | ❌ F-id failing | ⛔ BLOCKED BY F-id | ? untested

```
Mini App (new Telegram user)
├─ Onboarding (UI)
│  ├─ Замер (reps) -> "Да" -> "Продолжить"                          ✅ (resumes after reload)
│  └─ Анкета 5 шагов -> "Готово" -> trial (14 d) -> Home             ✅
├─ Главная
│  ├─ Каталог программ (cards)                                       ❌ F-01 (empty: "Каталог курсов появится здесь позже.")
│  │  ├─ Program Detail                                              ⛔ BLOCKED BY F-01
│  │  └─ Add / start program                                         ⛔ BLOCKED BY F-01
│  ├─ Своя программа (баннер) -> Новая тренировка                     ✅
│  ├─ Мои тренировки: Создать / list / open                          ✅
│  ├─ Баннер "Внести активность" -> Журнал + Записать                ✅
│  ├─ Баннер "Откройте план дня" -> Планы                            ❌ F-02 (loop)
│  ├─ Избранное (appears after "В избранное")                        ✅ (empty state has no screen: E8 untested as message)
│  └─ Тесты -> Максимум / Вис / Вес -> "Записать результат"          ✅ (form visible; not submitted — assessments forbidden in S0)
├─ Планы
│  ├─ Сейчас: no plan -> "Выбрать курс на Главной"                   ❌ F-02
│  ├─ Сейчас: plan from custom workout, week 1 "Текущая неделя"       ✅ (after 2nd add) / ❌ F-03 (first add lost)
│  │  ├─ + Добавить упражнение (day / pool)                          ✅ (needs >=1 exercise in library)
│  │  ├─ Действия: Перенести (день / свободный пул)                  ✅
│  │  ├─ Убрать из плана (template kept)                             ✅ / ❌ F-06 (journal title lost)
│  │  ├─ Скопировать неделю 1 -> 2                                   ✅
│  │  ├─ Следующая / предыдущая неделя, new empty week              ✅
│  │  ├─ Начать из плана -> Live -> Finish                           ✅
│  │  └─ Remove program / program rows / "program with no PlanItems" ⛔ BLOCKED BY F-01
│  ├─ Завершённые: "Завершённых курсов пока нет. Убранные из плана курсы появятся здесь." ✅ (no content to show)
│  └─ Мои тренировки                                                 ✅
├─ Редактор тренировки
│  ├─ Пусто -> "+ Добавить упражнение"                               ✅
│  ├─ Пустая библиотека -> "Создать своё" (after typing)             ✅ / ❌ F-04 (hidden), F-13
│  ├─ Протокол (повторения / время / максимум / интервалы)           ✅ (reps_sets 3x10 rest 1:00 used; others ? untested)
│  ├─ Сохранить -> detail -> reload                                  ✅
│  ├─ Начать (direct, no plan)                                       ✅
│  ├─ Добавить в план                                                ❌ F-03 (first), ✅ later
│  └─ Detail with 0 exercises: Начать disabled                       ❌ F-07
├─ Live session
│  ├─ Ready -> Начать -> Готов -> ввод повторов -> отдых -> пропустить ✅
│  ├─ Reload mid-session (restore, timer)                            ✅
│  ├─ "Завершить" -> effort -> summary                               ✅ (F-10 copy, F-11 domain question)
│  └─ Close -> Home                                                  ✅
├─ Журнал: entry (Свободная / По плану), sets, reps, effort         ✅ ; new context same initData ✅
├─ Аналитика: counters, per-exercise                                ✅ (F-09 raw "user")
├─ Профиль: данные, тесты, подписка, ачивки                          ✅ ; expired label ❌ F-08
└─ Expired user
   ├─ paywall / no_access                                            ❌ F-05
   └─ no crash / no dead UI                                          ✅
```
