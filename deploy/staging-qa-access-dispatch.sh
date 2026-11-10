#!/usr/bin/env bash
# Preserve all previous forced-command policy through the saved dispatcher.
set -euo pipefail
case "${SSH_ORIGINAL_COMMAND:-}" in
  './qa-staging.sh provision') exec /home/deploy/qa-staging.sh provision ;;
  './qa-staging.sh snapshot') exec /home/deploy/qa-staging.sh snapshot ;;
  *) exec /home/deploy/deploy-staging-dispatch.before-qa.sh ;;
esac
