# Реестр тестовых сущностей (Crimpd)
Правило: всё создаваемое в Crimpd называется `RESCAN TEST - ...`, записывается сюда сразу, удаляется в конце (если удаление возможно).
Прежний реестр REF-2: `~/android-ref-lab/TEST_DATA_LEDGER.md` (все объекты были удалены).
| ID | Дата | Что создано | Где | Статус |
|---|---|---|---|---|
| T-001 | 2026-10-21 | Custom workout «RESCAN TEST - Load» (Back Squat) + её лог 21 Oct | Crimpd Home → My Workouts / Logbook | DELETED 2026-10-22 (сначала лог с проверкой карточки, затем тренировка) |
| T-002 | 2026-10-22 | Лог «Weighted Pull-up Test» 8×2, +10 кг (дата 22 Oct 2026) — ТЕСТОВЫЙ, влияет на результат в Profile и на «% of 2RM» | Crimpd Logbook / Profile / Analytics | DELETED 2026-10-22 (Delete Log + подтверждение); проверено: «90% of 2RM» снова +47 кг; Profile снова «Weighted Pull-up Test: Jul 20, +60 kg» |
| T-003 | 2026-10-22 | Cross-Training log «Running 15m», note «RESCAN TEST cross» | Logbook | DELETED 2026-10-22 (проверено: Analytics Cross-Training 0) |
| T-004a/b | 2026-10-22 | ДВА одинаковых лога «Running 15m», note «RESCAN offline» (дубликат после сбоя сети и повторного Save) | Logbook | DELETED ×2 2026-10-22 (каждый перед удалением проверен по заметке) |

Инцидент процесса 2026-10-22: при удалении дубликатов серия слепых тапов по координатам открыла карточку РЕАЛЬНОГО лога владельца («подтягивания на фб», 21 Oct 10:30 PM). Delete Log на этой карточке не нажимался (ниже экрана, поиск «Delete Log» не нашёл), запись и её данные на месте — проверено повторным просмотром Logbook. Дальше удаление только после проверки заметки «RESCAN».
Остаётся: T-001 (RESCAN TEST - Load + её лог). Системные настройки эмулятора (font_scale, night mode, сеть) возвращены к исходным.
| T-005 | 2026-10-22 | Training plan «RESCAN TEST - Plan» (blank, 6 weeks, start Nov 2) | Training Plans → Upcoming | DELETED 2026-10-22 (Delete Training Plan + подтверждение); Upcoming пуст, реальный план «In Progress» цел |
| T-006 | 2026-10-22 | Custom exercise «RESCAN Exercise» + workout «RESCAN TEST - CustomEx» | Home → My Workouts | DELETED 2026-10-22 (Delete Workout без подтверждения) |
| T-001b | 2026-10-22 | ДВА лога «RESCAN TEST - Load» (22 Oct 11:39) от double-tap Save | Logbook | DELETED ×2 2026-10-22; проверено: у тренировки остался только лог T-001 от 21 Oct |

## Итоговая проверка после чистки (2026-10-22, UI эмулятора)
- Поиск «RESCAN» на Home: FOUND 0 WORKOUTS; в Logbook нет записей «RESCAN» (3 прокрутки).
- Analytics (1 Mo.): Cross-Training 0; TOTAL 27 / 471 / 78 / 32 (workouts / duration / TUT / workload) — арифметически = значение с моими логами (29 / 499 / 79 / 52) минус T-001 (1 / 3 / ~0 / 0) и T-002 (1 / 25 / 1 / 20); изначального снимка до скана нет (INFERRED, что это исходное состояние).
- Profile: Weighted Pull-up Test снова «Jul 20, 2026, +60 kg»; In Progress-план владельца на месте (Week 5 of 6).
- Системные настройки эмулятора возвращены (font_scale 1.0, night no, сеть включена).
- Реальные данные владельца не менялись; единственный инцидент процесса — см. выше (карточка реального лога была открыта и закрыта без изменений).
| T-007 | 2026-10-22 | Training plan «RESCAN TEST - Past» (6 нед., старт Mon Jan 5, 2026 — в прошлом, не пересекается) | Training Plans → Completed | DELETED 2026-10-23 после входа владельца (название и даты сверены) |
| T-008 | 2026-10-22 | Лог «Weighted Pull-up Test» с датой 6 Jan 2026 (в неделе 1 плана T-007), результат ≈+5 кг (проверить) | Logbook (Jan 2026) / Profile | DELETED 2026-10-23: карточка сверена (Tue Jan 6 2026, 8×2, +5 кг, Easy, 12:00 AM), единственная запись на 6 января |
| T-009 | 2026-10-22 | Plan «RESCAN TEST - Past (Copy)» (клон T-007, старт Nov 2) | Training Plans → Upcoming | DELETED 2026-10-23 после входа владельца (название и даты сверены) |

## ВАЖНО (2026-10-22 ~12:39 локального времени эмулятора): Crimpd разлогинился
Остались на сервере аккаунта владельца тестовые сущности (все с именем RESCAN TEST): план T-007 «RESCAN TEST - Past» (Jan 5 – Feb 9 2026), план T-009 «RESCAN TEST - Past (Copy)» (старт Nov 2 2026), лог T-008 «Weighted Pull-up Test» от 6 Jan 2026 (результат ≈5 кг; на Profile не влияет, т.к. по дате старше +60 кг от 20 Jul). Удаляются без подтверждения владельцу в UI: Plans → план → … → Delete Training Plan; лог — Logbook (январь 2026) или карточка теста → Delete Log. Реальные данные владельца не менялись.

## Очистка после входа владельца (2026-10-23)
- Аккаунт тот же (профиль: те же возраст/рост/вес и результаты тестов; личные данные в репозиторий не записываются).
- Удалены: T-009 план «RESCAN TEST - Past (Copy)» (Upcoming, Nov 2), T-007 план «RESCAN TEST - Past» (Completed, Jan 5 – Feb 9), T-008 лог Weighted Pull-up Test от 6 Jan 2026 (+5 кг). Каждое — после сверки названия/дат; у лога единственная запись на 6 января.
- Проверено: Profile «Weighted Pull-up Test» снова Jul 20 2026, +60 кг; Finger Strength Test Jul 23, +40 кг; реальный план «In Progress» (Week 5 of 6, 0/7) на месте; Upcoming пуст; Completed содержит только планы владельца.
- Наблюдение: удаление плана T-007 не удалило лог T-008 (лог пережил удаление плана) — перепроверено в Logbook до удаления лога.
| T-010 | 2026-10-23 | Plan «RESCAN TEST - Template» (из шаблона Bouldering Mastery, старт Mon Jan 5 2026) | Training Plans → Completed | DELETED 2026-10-23 |
| T-011 | 2026-10-23 | Лог «Finger Strength Test» от 6 Jan 2026, +10 кг, 8×1 (в плане T-010, неделя 1) | Logbook (Jan 2026) | DELETED 2026-10-23 |
| T-012 | 2026-10-23 | Лог «Weighted Pull-up Test» от 7 Jan 2026, +3 кг, 8×2 (в плане T-010, неделя 1) | Logbook (Jan 2026) | DELETED 2026-10-23 |
| T-013 | 2026-10-23 | Custom workout «RESCAN TEST - W2» | Home → My Workouts | DELETED 2026-10-23 |
| T-014 | 2026-10-23 | Лог «RESCAN TEST - W2» от 23 Oct (reps 2 у первого упражнения, заметки «RESCAN exercise note»/«RESCAN workout note») | Logbook | DELETED 2026-10-23 |
| T-015 | 2026-10-23 | Open Climbing «Session Review» лог (Indoor/Boulder, 15m, Easy, 1 problem, grade 5) | Logbook | DELETED 2026-10-23 |
| T-016 | 2026-10-23 | Лог «RESCAN TEST - W2» с БУДУЩЕЙ датой (28 Oct 2026) | Logbook | DELETED 2026-10-23 |

## Уборка 2026-10-23 (проход 2, после входа)
Удалены (каждая — после сверки по названию/дате/значениям): T-010 план «RESCAN TEST - Template» (Completed), T-011 лог Finger Strength Test (Aug 4 2026, +10 кг, ранее Jan 6), T-012 лог Weighted Pull-up Test (Jan 7 2026, +3 кг), T-013 тренировка «RESCAN TEST - W2», T-014 лог W2 от 23 Oct (25%), T-016 лог W2 с датой 28 Oct (будущей), T-015 лог Open Climbing (23 Oct 12:00 PM, grade 5, 1 problem; заметка «RESCAN climb note» в карточке не отображается — идентификация по дефолтам формы и времени, единственная запись Indoor Bouldering за день).
Финальная проверка: см. блок «Итоговая проверка 2» ниже.
| T-017 | 2026-10-23 | Лог «Finger Strength Test – One Arm» от 6 Jan 2026, +8 кг | Logbook/Profile | DELETED 2026-10-23 (единственный лог теста; +8 кг, Jan 6 сверены) |
| T-018 | 2026-10-23 | Plan «RESCAN TEST - Edit» (blank, 6 нед., Jan 5 2026) | Training Plans → Completed | DELETED 2026-10-23 |
| T-019 | 2026-10-23 | Cross-Training «Running 15m» note «RESCAN K07» (тест офлайн-Save) | Logbook | DELETED 2026-10-23 (2 записи: оригинал и клон, сверены по времени 12:50–12:51 PM) |
| T-020 | 2026-10-23 | Plan «RESCAN TEST - Duration» (blank, 6 нед., Jan 5 2026) | Training Plans → Completed | DELETED 2026-10-23 |
| T-021 | 2026-10-23 | Лог «7:3s 30%» от 3 Feb 2026 (неделя 5 плана T-020) | Logbook | DELETED 2026-10-23 |
| T-022 | 2026-10-23 | Лог «Finger Strength Test» от 5 Aug 2026 +5 кг, заметка упражнения «RESCAN G08 note» | Logbook/Profile | DELETED 2026-10-23 |
| T-023 | 2026-10-23 | Второй лог «Finger Strength Test» от 5 Aug 2026 +15 кг (тест «два лога в один день») | Logbook/Profile | DELETED 2026-10-23 |
| T-024 | 2026-10-23 | Третий лог «Finger Strength Test» от 5 Aug 2026 +10 кг | Logbook/Profile | DELETED 2026-10-23 |
| T-025 | 2026-10-23 | Custom workout «RESCAN TEST - XA» (Back Squat) | Home → My Workouts | DELETED 2026-10-23 |
| T-026 | 2026-10-23 | Custom workout «RESCAN TEST - XB» (Back Squat) | Home → My Workouts | DELETED 2026-10-23 |

## Итоговая проверка 2 (2026-10-23, конец прохода)
- Все T-001…T-026 удалены (каждая — после сверки названия/даты/значений). Поиск «RESCAN» на Home: FOUND 0.
- Profile: Finger Strength Test — Jul 23 2026, +40 кг; Weighted Pull-up Test — Jul 20 2026, +60 кг (исходные). Реальный план «In Progress» на месте (Week 5 of 6, 0/7); Upcoming пуст; в Completed только планы владельца.
- Кратковременные ложные пустые состояния списков (после удаления плана/офлайн) НЕ означали потерю данных — после перезапуска всё на месте (OBS-0098, OBS-0106).
- Системные настройки эмулятора возвращены: сеть включена, wm size/density сброшены (1080x2400/420), font_scale 1.0, night mode no. Chrome (открывался из «Help») без входа, уведомления/cookies отклонены, процесс остановлен.
- Изменения аккаунта владельца: ни одна настройка (Theme, Vibrations, Volume, единицы, профиль) не менялась. Favorite на Edge Lift Test включён и выключен (исходное состояние восстановлено).
