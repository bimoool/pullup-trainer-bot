#!/usr/bin/env bash
# Снять экраны НАШЕГО приложения для сравнения с эталоном (docs/REFERENCE_UX_REVIEW.md).
# Требует поднятый локальный сервер (см. webapp-frontend/e2e/README.md) и BOT_TOKEN=e2e-test-token.
# Usage: scripts/ux_capture.sh <label> [outdir]   # label: before | after | любое
# Сиды пересоздаются перед каждой шириной (одна активная сессия на пользователя).
set -euo pipefail
LABEL="${1:?label}"; OUT="${2:-ux-captures}"
export PYTHONPATH="${PYTHONPATH:-.}" PYTHON="${PYTHON:-python}"
CONFIG="${UX_PW_CONFIG:-playwright.config.ts}"
for W in ${UX_WIDTHS:-390 320}; do
  bash scripts/e2e_seed_all.sh >/dev/null
  (cd webapp-frontend/e2e && UX_CAPTURE=1 UX_LABEL="$LABEL" UX_WIDTHS="$W" UX_CAPTURE_DIR="$OUT" \
    npx playwright test -c "$CONFIG" scenarios/ux-capture.spec.ts)
done
echo "captures: $OUT/$LABEL/{390,320}/*.png|txt"
