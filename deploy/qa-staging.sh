#!/usr/bin/env bash
# Installed outside the checkout; only reserved synthetic QA identities are addressed.
set -euo pipefail
[[ $# == 1 ]] || exit 2
case "$1" in
  provision) extra=() ;;
  snapshot) extra=(--snapshot) ;;
  *) echo 'Only provision or snapshot is allowed' >&2; exit 2 ;;
esac
cd /home/deploy/pullup-trainer-bot-staging
exec 9>/home/deploy/.deploy-staging.lock
flock -n 9 || { echo 'Staging is busy' >&2; exit 1; }
# Explicit project/config avoids inherited compose overrides. The provisioner independently
# requires a staging DB/host and refuses every identity outside its reserved QA range.
exec env -u COMPOSE_FILE -u COMPOSE_PROJECT_NAME -u DOCKER_HOST -u DOCKER_CONTEXT \
  docker compose -f docker-compose.yml -p pullup-staging run --rm --no-deps \
  -e QA_ALLOW_STAGING=1 app python -m scripts.qa.provision_staging_identities "${extra[@]}"
