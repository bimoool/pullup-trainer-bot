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
lock=/home/deploy/.deploy-staging.lock
lock_fd=
# util-linux flock in authorized_keys passes its locked open-file description to
# the child. Reuse that description, but still acquire/verify the lock ourselves.
# Opening a second description would conflict with the inherited outer lock.
for descriptor in /proc/$$/fd/[0-9]*; do
  if [[ "$descriptor" -ef "$lock" ]]; then
    lock_fd="${descriptor##*/}"
    break
  fi
done
if [[ -z "$lock_fd" ]]; then
  exec 9>"$lock"
  lock_fd=9
fi
flock -n "$lock_fd" || { echo 'Staging is busy' >&2; exit 1; }
# Explicit project/config avoids inherited compose overrides. The provisioner independently
# requires a staging DB/host and refuses every identity outside its reserved QA range.
exec env -u COMPOSE_FILE -u COMPOSE_PROJECT_NAME -u DOCKER_HOST -u DOCKER_CONTEXT \
  docker compose -f docker-compose.yml -p pullup-staging run --rm --no-deps \
  -e QA_ALLOW_STAGING=1 app python -m scripts.qa.provision_staging_identities "${extra[@]}"
