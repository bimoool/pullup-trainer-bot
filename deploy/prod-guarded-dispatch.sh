#!/usr/bin/env bash
# Forced command ОТДЕЛЬНОГО SSH-ключа, которым GitHub Actions вызывает guarded-выкат production
# (.github/workflows/production-deploy.yml и production-rollback.yml). Не ключ deploy.yml и не staging-ключи.
# Ставится на VPS скриптом deploy/install-prod-actions-access.sh как /root/bin/prod-guarded-dispatch.sh и
# прописывается в /root/.ssh/authorized_keys одной строкой:
#   restrict,command="/root/bin/prod-guarded-dispatch.sh" ssh-ed25519 AAAA… gh-actions-prod-guarded
#
# Принимает ровно четыре литеральных шаблона, всё остальное отклоняется (forced-command не расширяется и не обходится):
#   prod-guarded <40-hex-sha> preflight <from-rev-12hex> <to-rev-12hex>
#   prod-guarded <40-hex-sha> apply <from-rev-12hex> <to-rev-12hex> PRODUCTION-APPLY-<первые 12 hex sha>
#   prod-rollback <R1|R3> /root/backups/<имя>.manifest check
#   prod-rollback <R1|R3> /root/backups/<имя>.manifest apply ROLLBACK-<R1|R3>-<run_id>
# Сами проверки (бэкапы, перенос данных, инварианты, fail-safe, токены подтверждения) делают установленные рядом
# /root/bin/deploy-production-guarded-run.sh и /root/bin/rollback-production-guarded.sh — этот файл только разбирает
# команду и передаёт им аргументы из regex. Окружение вызывающего не пропускается (env -i): из SSH в скрипты попадают
# только ожидаемые ревизии Alembic, которые guarded-скрипт сверяет с живой БД и с выкатываемым SHA.
set -euo pipefail

BIN=/root/bin
LOCK_DIR=/root/backups
cmd="${SSH_ORIGINAL_COMMAND:-}"

re_deploy='^prod-guarded ([0-9a-f]{40}) (preflight|apply) ([0-9a-f]{12}) ([0-9a-f]{12})( (PRODUCTION-APPLY-[0-9a-f]{12}))?$'
re_rollback='^prod-rollback (R1|R3) (/root/backups/[A-Za-z0-9._-]+\.manifest) (check|apply)( (ROLLBACK-R[13]-prod-[0-9a-f]{7}-[0-9TZ]+-[0-9]+))?$'

clean_env=(env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOME=/root LANG=C.UTF-8)

mkdir -p "$LOCK_DIR"
exec 9>"$LOCK_DIR/.prod-actions.lock"
flock -n 9 || { echo "another production run started from GitHub Actions is in progress" >&2; exit 1; }

if [[ "$cmd" =~ $re_deploy ]]; then
  sha="${BASH_REMATCH[1]}"; mode="${BASH_REMATCH[2]}"; from="${BASH_REMATCH[3]}"; to="${BASH_REMATCH[4]}"; token="${BASH_REMATCH[6]}"
  if [ "$mode" = "preflight" ] && [ -n "$token" ]; then echo "rejected: preflight takes no token" >&2; exit 1; fi
  if [ "$mode" = "apply" ] && [ -z "$token" ]; then echo "rejected: apply requires the confirmation token" >&2; exit 1; fi
  args=("$sha" "$mode"); [ -n "$token" ] && args+=("$token")
  exec "${clean_env[@]}" PROD_EXPECTED_FROM_REV="$from" PROD_EXPECTED_TO_REV="$to" \
    "$BIN/deploy-production-guarded-run.sh" "${args[@]}"
fi

if [[ "$cmd" =~ $re_rollback ]]; then
  kind="${BASH_REMATCH[1]}"; manifest="${BASH_REMATCH[2]}"; mode="${BASH_REMATCH[3]}"; token="${BASH_REMATCH[5]}"
  [[ "$manifest" != *..* ]] || { echo "rejected: manifest path" >&2; exit 1; }
  if [ "$mode" = "check" ] && [ -n "$token" ]; then echo "rejected: check takes no token" >&2; exit 1; fi
  if [ "$mode" = "apply" ] && [ -z "$token" ]; then echo "rejected: apply requires the confirmation token" >&2; exit 1; fi
  args=("$kind" "$manifest" "$mode"); [ -n "$token" ] && args+=("$token")
  exec "${clean_env[@]}" "$BIN/rollback-production-guarded.sh" "${args[@]}"
fi

echo "rejected command: ${cmd}" >&2
exit 1
