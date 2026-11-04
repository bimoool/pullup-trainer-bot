#!/usr/bin/env bash
# Keep current pins by default. Dependency upgrades are a separate reviewed change.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $(uv --version) == 'uv 0.13.4'* ]] || { echo 'Install uv==0.13.4 before regenerating locks' >&2; exit 1; }
constraints=$(mktemp)
build_constraints=$(mktemp)
trap 'rm -f "$constraints" "$build_constraints"' EXIT
cp requirements/dev.txt "$constraints"
cp requirements/build.txt "$build_constraints"
for mode in runtime web dev; do
  extras=()
  if [[ "$mode" != runtime ]]; then extras+=(--extra web); fi
  if [[ "$mode" == dev ]]; then extras+=(--extra dev); fi
  uv pip compile pyproject.toml --universal --python-version 3.12 \
    "${extras[@]}" --constraint "$constraints" --generate-hashes --no-annotate \
    --output-file "requirements/$mode.txt" --custom-compile-command 'bash scripts/lock-python.sh'
done
uv pip compile requirements/build.in --universal --python-version 3.12 --constraint "$build_constraints" \
  --generate-hashes --no-annotate --output-file requirements/build.txt \
  --custom-compile-command 'bash scripts/lock-python.sh'
