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
