# Wave 13 captures (#280 criterion 1, #277)

Source: `develop/current` @650e82d (merge of #293 R-4 follow-ups), local build, seeded users, Chromium at device scale 1.
Produced by `UX_CAPTURE=1 scripts/ux_capture.sh <label>` (`webapp-frontend/e2e/scenarios/ux-capture.spec.ts`, opt-in) once per theme (`UX_THEME=light|dark`, `UX_WIDTHS=320|390`); PNGs are palette-quantized (96 colours) and renamed.
Tab screens are full-page captures (the sticky tab bar therefore appears mid-image); Live/Tests/Collections are viewport captures (320x640 / 390x844).

**Before/after:** no earlier capture set is committed in the repo or docs (REFERENCE_UX_REVIEW.md only describes the procedure, labels `before|after`); so only the **after** set exists. The pre-wave state is described textually in `CRIMPD_VISUAL_GAP.md` («Наше сейчас» column). Reference images: `~/android-ref-lab/REF_2_1/screens_shareable/` (not committed).

Files: `docs/captures/wave13/<theme>-<width>/<screen>.png` (themes light, dark; widths 320, 390). Every screen exists for all 4 combinations.

| Screen | 320 light | 320 dark | 390 light | 390 dark | Observation vs reference |
|---|---|---|---|---|---|
| Главная | [png](light-320/home.png) | [png](dark-320/home.png) | [png](light-390/home.png) | [png](dark-390/home.png) | Баннер/ряды программ по категориям, поиск-пилюля + «+», «Подборки», «Мои тренировки»; как референс — поиск сверху, карточки с категориями; нет героя-фото (C). |
| Workout Detail | [png](light-320/workout-detail.png) | [png](dark-320/workout-detail.png) | [png](light-390/workout-detail.png) | [png](dark-390/workout-detail.png) | Герой + «Начать / Записать / Добавить в план / Изменить» + Упражнения + История — анатомия референса (Start/Log/Favorite/Add to Plan); нет видео Overview и поля Description (нет данных). |
| Планы | [png](light-320/plans.png) | [png](dark-320/plans.png) | [png](light-390/plans.png) | [png](dark-390/plans.png) | «Сейчас/Завершённые», карточка текущего плана, неделя с группами по дням и «Начать»; в референсе «Training Plans» проще, у нас богаче. |
| Журнал | [png](light-320/journal.png) | [png](dark-320/journal.png) | [png](light-390/journal.png) | [png](dark-390/journal.png) | Календарь + плотный компактный список записей с бейджем «По плану», открывает шторку (Просмотр/Правка/Клон как в Training History); длинный список без группировки по дням в кадре. |
| Аналитика | [png](light-320/analytics.png) | [png](dark-320/analytics.png) | [png](light-390/analytics.png) | [png](dark-390/analytics.png) | Табы метрик, диапазоны 1/3 мес/Свой, «По типам» (кольцо) и «по неделям», сводка; структура референса (Logged by Type/Week), легенда компактнее. |
| Профиль | [png](light-320/profile.png) | [png](dark-320/profile.png) | [png](light-390/profile.png) | [png](dark-390/profile.png) | Карточка с цифрами, личные данные, Тесты, Аккаунт, разряды ГТО/WSF; в референсе это Hamburger-меню — у нас вкладка. |
| Тесты | [png](light-320/tests.png) | [png](dark-320/tests.png) | [png](light-390/tests.png) | [png](dark-390/tests.png) | Список тестов-карточек со статусом и шевроном, «назад»; доступен с Главной и из Профиля. |
| Live: пред-экран | [png](light-320/live-1-pre.png) | [png](dark-320/live-1-pre.png) | [png](light-390/live-1-pre.png) | [png](dark-390/live-1-pre.png) | Эйбрау, название, мета, карточки упражнений, закреплённое «Начать» (аналог exec_prestart без видео). |
| Live: работа | [png](light-320/live-2-work.png) | [png](dark-320/live-2-work.png) | [png](light-390/live-2-work.png) | [png](dark-390/live-2-work.png) | Крупная цель «8 повт.», панель записи, закреплённое «Готово»; как exec_running, без медиа. На 320x640 при фокусе поля верх может быть слегка прокручен. |
| Live: отдых | [png](light-320/live-3-rest.png) | [png](dark-320/live-3-rest.png) | [png](light-390/live-3-rest.png) | [png](dark-390/live-3-rest.png) | Огромный таймер 1:00, «Пропустить отдых», «Пауза», кнопка «Предыдущий подход» (#292), правка прошлого подхода. |
| Live: шторка итога | [png](light-320/live-4-review.png) | [png](dark-320/live-4-review.png) | [png](light-390/live-4-review.png) | [png](dark-390/live-4-review.png) | Нижняя шторка «Как прошла тренировка?» 1-5 + заметка (Effort как в Log Workout). |
| Live: итог | [png](light-320/live-5-summary.png) | [png](dark-320/live-5-summary.png) | [png](light-390/live-5-summary.png) | [png](dark-390/live-5-summary.png) | Герой «Тренировка завершена», 2 счётчика, блоки, «Закрыть»; аналог exec_finished. |
| Настройки | [png](light-320/settings.png) | [png](dark-320/settings.png) | [png](light-390/settings.png) | [png](dark-390/settings.png) | Группы-секции со строками, нативные контролы, Сохранить/Отмена внизу; у референса настроек в Mini App-виде нет. |
| Подборки (ряд на Главной) | [png](light-320/collections-row.png) | [png](dark-320/collections-row.png) | [png](light-390/collections-row.png) | [png](dark-390/collections-row.png) | Ряд «Подборки» с карточкой автора/названия/состава; у референса нет прямого аналога (Playlist detail). |
| Подборка (деталь) | [png](light-320/collection-detail.png) | [png](dark-320/collection-detail.png) | [png](light-390/collection-detail.png) | [png](dark-390/collection-detail.png) | Герой + «Подборка», описание и список программ/упражнений с шевронами; аналог playlist_detail. |

No horizontal overflow was visible in any of the 60 images; the programmatic overflow assertions are in `parity/full-sweep.spec.ts`, `visual-*.spec.ts`.
Not captured here (covered by specs only): Live error/pending states (`parity/r4-followup.spec.ts`: pre-screen «Повторить»/«Назад», «Завершение … ещё отправляется…»).
