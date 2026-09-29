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
seed builder_workouts 910001
seed journal_v2 910002
seed analytics_v2 910003
seed home_workouts 920001
seed home_workouts 920002
seed golden_journey 930001
