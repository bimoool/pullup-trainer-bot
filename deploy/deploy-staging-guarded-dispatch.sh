#!/usr/bin/env bash
# Forced command ОТДЕЛЬНОГО SSH-ключа guarded staging-деплоя (не ключа deploy-staging.yml и не прод-ключа).
# Копия для ревью; на VPS ставится вручную как /home/deploy/deploy-staging-guarded-dispatch.sh и прописывается в authorized_keys
# одной строкой (docs/STAGING_RC_RUNBOOK.md §3.2):
#   command="/home/deploy/deploy-staging-guarded-dispatch.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA… guarded-staging
#
# Принимает ровно один литеральный паттерн (как существующие dispatch-скрипты, forced-command не обходится и не расширяется):
#   ./deploy-staging-guarded.sh <40-hex-sha> <preflight|dry-run|apply> <yes|no> [<users.id,users.id,...>|-]
# Всё остальное отклоняется. Параллельные запуски исключены блокировкой.
set -euo pipefail

cmd="${SSH_ORIGINAL_COMMAND:-}"
re='^\./deploy-staging-guarded\.sh ([0-9a-f]{40}) (preflight|dry-run|apply) (yes|no)( (-|[0-9]+(,[0-9]+){0,99}))?$'
if [[ ! "$cmd" =~ $re ]]; then
  echo "rejected command: ${cmd}" >&2
  exit 1
fi

exec 9>/home/deploy/.deploy-staging-guarded.lock
flock -n 9 || { echo "another guarded staging deploy is running" >&2; exit 1; }
exec /home/deploy/deploy-staging-guarded-run.sh "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}" "${BASH_REMATCH[5]:--}"
