#!/usr/bin/env bash
# Все сиды современных E2E-сценариев (webapp-frontend/e2e/scenarios). Идемпотентно:
# каждый вызов e2e_seed.py стирает и пересоздаёт данные своего telegram_id.
# Используется и в CI (.github/workflows/e2e.yml), и локально — один источник правды.
# not_onboarded (900001) не сеет ничего: статус = отсутствие строки users.
set -euo pipefail
# e2e_seed.py импортирует пакет scripts.* — корень репозитория должен быть в sys.path.
export PYTHONPATH="${PYTHONPATH:-.}"
PY="${PYTHON:-python}"
seed() { "$PY" scripts/e2e_seed.py "$1" "$2"; }
seed first_workout 900002
seed ready 900003
seed v2_session_ready 900010
seed v2_session_complex 900011
seed v2_session_progression_edit 900012
seed plan_week_ready 900013
seed plan_week_grouping 900014
seed plan_week_add_exercise 900015
seed plan_week_start_session 900016
seed plan_week_manual_session 900017
seed journal_combined 900018
seed plan_week_stepper 990001
seed plan_week_stepper 990002
seed builder_workouts 910001
seed journal_v2 910002
seed journal_calendar 970001
seed journal_calendar 970002
seed journal_edit 997201
seed journal_edit 997202
seed analytics_v2 910003
seed analytics_metric 995001
seed analytics_metric 995002
seed tests_hub 996001
seed tests_hub 996002
seed tests_hub 996011
seed tests_hub 996012
seed peer_cohort_female 994001
seed peer_cohort_male 994002
seed peer_insufficient 994011
seed peer_insufficient 994012
seed peer_empty 994021
seed peer_empty 994022
seed peer_empty 994031
seed peer_empty 994032
seed home_workouts 920001
seed home_workouts 920002
seed home_workouts 920003
seed home_workouts 920004
seed home_discovery 940001
seed home_discovery 940002
seed workout_detail 950001
seed workout_detail 997101
seed workout_detail 997102
seed workout_detail 997103
seed workout_detail 997104
seed home_discovery 960001
seed home_discovery 960002
seed home_discovery 960003
seed home_discovery 960004
seed home_discovery 960005
seed home_discovery 960006
seed home_discovery 960007
seed home_discovery 960008
seed golden_journey 930001
seed session_recovery 930002
seed session_recovery 930003
seed session_recovery 930004
seed session_recovery 930005
seed session_recovery 930006
seed session_recovery 930007
seed golden_journey 980001
seed golden_journey 980002
seed golden_journey 980011
seed golden_journey 980012
# Journal log (#263): 985001/985002 (320px, + retry), 985011/985012 (390px), Главная → «+»: id+5(+retry).
for id in 985001 985002 985006 985007 985011 985012 985016 985017; do seed golden_journey "$id"; done
seed golden_journey 980021
seed golden_journey 980022
seed golden_journey 980031
seed golden_journey 980032
# #265 «Live logging panel»: длинный отдых (session_recovery, 60 с) и короткий (golden_journey, 2 с).
seed session_recovery 980041
seed session_recovery 980042
seed session_recovery 980051
seed session_recovery 980052
seed golden_journey 980061
seed golden_journey 980062
seed golden_journey 980071
seed golden_journey 980072
# #266 «Plans overview»: 9901xx — только чтение (320/390), 9902xx — мутирующий сценарий «Убрать курс из плана».
seed plans_overview 990101
seed plans_overview 990102
seed plans_overview 990201
seed plans_overview 990202
# #275 «Plans schedule»: 990301 (320 light) / 990302 (390 dark) — мутирующий сценарий.
seed plan_week_manual_session 990301
seed plan_week_manual_session 990302
# #283 «Plans current week»: 990401/990411 (320 light / 390 dark, + retry) — мутирующий сценарий.
for id in 990401 990402 990411 990412; do seed golden_journey "$id"; done
# #273 «Workout Detail start/log»: 998001/998011 (+ retry), «Записать»: id+5(+retry).
for id in 998001 998002 998006 998007 998011 998012 998016 998017; do seed golden_journey "$id"; done
# Settings (#268): 999001/999011 (единицы), +2 (тема), +4 (отмена), каждый + retry (id+1).
for id in 999001 999002 999003 999004 999005 999006 999011 999012 999013 999014 999015 999016; do seed ready "$id"; done
# Background timer (#269): отдых 60 с (session_recovery) и interval 180 с; каждый + retry (id+1).
for id in 999101 999102 999111 999112; do seed session_recovery "$id"; done
for id in 999121 999122 999131 999132; do seed background_interval "$id"; done
# Body metrics (#270): 999201/999211 (экран+тренд), +2 (правка/удаление), каждый + retry (id+1).
for id in 999201 999202 999203 999204 999211 999212 999213 999214; do seed body_metrics "$id"; done
# Analytics distribution (#274): 999301/999311 (320/390 px, только чтение), каждый + retry (id+1).
for id in 999301 999302 999311 999312; do seed analytics_distribution "$id"; done
# Full sweep (#277): пустые (RO) 999901-999904 = 320 light / 320 dark / 390 light / 390 dark; наполненные RO — 999911-999914;
# мутирующие потоки — наполненные: 99992x (тренировка → журнал → аналитика → экспорт), 99993x (тесты),
# 99994x (настройки/единицы), 99995x (планы: будущая неделя/копирование/перенос); те же 4 комбинации (x1-x4);
# retry — +10000 (1009901…). Диапазон 9999xx зарезервирован под sweep (занят: 9995xx #280, 9996xx #282, 9997xx #284/#277-defects).
for retry in 0 10000; do
  for id in 999901 999902 999903 999904; do seed sweep_empty $((id + retry)); done
  for id in 999911 999912 999913 999914 999921 999922 999923 999924 999931 999932 999933 999934 999941 999942 999943 999944 999951 999952 999953 999954; do
    seed sweep_populated $((id + retry))
  done
done
# Visual shell (#280): 9995xx — только чтение (320/390 × light/dark), каждый + retry (id+1).
for id in 999501 999502 999511 999512 999521 999522 999531 999532; do seed home_discovery "$id"; done
# Residual gaps (#281): 9973xx — Журнал → «Открыть тренировку» (workout_detail), Главная «Все ›» + тесты в поиске
# (home_discovery, только чтение), 9974xx — вибрация конца фазы (golden_journey, отдых 2 с); каждый + retry (id+1).
for id in 997301 997302 997311 997312; do seed workout_detail "$id"; done
for id in 997321 997322 997331 997332; do seed home_discovery "$id"; done
for id in 997401 997402 997403 997404 997411 997412 997413 997414; do seed golden_journey "$id"; done
# Collections (#271): 999401/999402 (320 px light, + retry), 999411/999412 (390 px dark, + retry); read-only.
for id in 999401 999402 999411 999412; do seed collections "$id"; done
# Owner P0 (#279) «Факультатив — 3 минуты подтягиваний»: 999801 (320 px light) / 999811 (390 px dark), каждый + retry (id+1).
for id in 999801 999802 999811 999812; do seed owner_optional_workout "$id"; done
# #282 «Journal dedupe»: 999601 (320 px light, + retry) / 999611 (390 px dark, + retry); правка и удаление legacy-записей (#284).
for id in 999601 999602 999611 999612; do seed journal_dedupe "$id"; done
# #277 «Sweep defects» (D1-D3): 997501 (320 px light) / 997521 (390 px dark); тесты берут id + 2*индекс + retry.
for base in 997501 997521; do for off in 0 1 2 3 4 5 6 7 8 9; do seed sweep_defects $((base + off)); done; done
# Visual live session (#280, Live Session stream): 9976xx — 320/390 × light/dark, каждый + retry (id+1);
# 997691/997692 — только для снимков (ux-capture), не для тестов.
for id in 997601 997602 997611 997612 997621 997622 997631 997632 997691; do seed session_recovery "$id"; done
seed builder_workouts 997692
# Visual secondary screens (#280, tier 3): 9977xx — только чтение (320/390 × light/dark делят пользователя), без retry.
seed builder_workouts 997701
seed home_discovery 997702
seed collections 997703
seed body_metrics 997704
seed ready 997706
seed tests_hub 997707
# #284 C «Journal return»: 999701 (320 px light, + retry) / 999711 (390 px dark, + retry); мутаций нет.
for id in 999701 999702 999711 999712; do seed journal_return "$id"; done
# #285 A «Live UX»: 9978xx — 320/390 × light/dark, на тест id + 2*индекс + retry (≤ +9); session_recovery.
for base in 997801 997811 997821 997831; do for off in 0 1 2 3 4 5 6 7 8 9; do seed session_recovery $((base + off)); done; done
# #224 «Платформа Telegram» (tg-platform.spec.ts): 998801 BackButton, 998803 closing confirmation (live), 998805 safe-area/theme,
# каждый + retry (id+1); 998811 — десятичный ввод «12,5» (ready: вес/рост профиля есть).
for id in 998801 998802 998803 998804 998805 998806; do seed session_recovery "$id"; done
for id in 998811 998812; do seed ready "$id"; done
