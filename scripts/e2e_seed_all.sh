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
# Visual shell (#280): 9995xx — только чтение (320/390 × light/dark), каждый + retry (id+1).
for id in 999501 999502 999511 999512 999521 999522 999531 999532; do seed home_discovery "$id"; done
# Collections (#271): 999401/999402 (320 px light, + retry), 999411/999412 (390 px dark, + retry); read-only.
for id in 999401 999402 999411 999412; do seed collections "$id"; done
# Owner P0 (#279) «Факультатив — 3 минуты подтягиваний»: 999801 (320 px light) / 999811 (390 px dark), каждый + retry (id+1).
for id in 999801 999802 999811 999812; do seed owner_optional_workout "$id"; done
# Visual live session (#280, Live Session stream): 9976xx — 320/390 × light/dark, каждый + retry (id+1);
# 997691/997692 — только для снимков (ux-capture), не для тестов.
for id in 997601 997602 997611 997612 997621 997622 997631 997632 997691; do seed session_recovery "$id"; done
seed builder_workouts 997692
