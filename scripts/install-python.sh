#!/usr/bin/env bash
# Install a complete, hashed dependency set, then build only the local project.
set -euo pipefail
cd "$(dirname "$0")/.."
mode=${1:-dev}
case "$mode" in runtime) extras='.' ;; web) extras='.[web]' ;; dev) extras='.[dev,web]' ;; *) echo 'Usage: bash scripts/install-python.sh runtime|web|dev' >&2; exit 2 ;; esac
python_bin=${PYTHON:-python}
"$python_bin" -m pip install --require-hashes --only-binary=:all: --no-deps -r requirements/build.txt -r "requirements/$mode.txt"
"$python_bin" -m pip install --no-deps --no-build-isolation -e "$extras"
"$python_bin" -m pip check
