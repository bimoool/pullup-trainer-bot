#!/usr/bin/env bash
set -euo pipefail

# Форсированная SSH-команда (authorized_keys `command=`) для ОТДЕЛЬНОГО
# ключа, заведённого только под staging-деплой (issue #169) — сознательно
# НЕ трогает существующий production-ограничивающий wrapper (deploy-dispatch.sh
# на сервере, не версионируется в этом репозитории, см. docstring
# deploy-run.sh рядом) — новый ключ добавляется ВТОРОЙ строкой в
# authorized_keys для того же пользователя deploy, ничего не меняя в уже
# существующей прод-строке:
#
#   command="/home/deploy/deploy-staging-dispatch.sh",no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA... staging-deploy
#
# Приватная половина этого ключа — новый GitHub Actions secret
# VPS_STAGING_DEPLOY_SSH_KEY, используется ТОЛЬКО в deploy-staging.yml,
# никогда в deploy.yml (производственный ключ VPS_DEPLOY_SSH_KEY остаётся
# как есть, со своим отдельным ограничением на `./deploy.sh <sha>`).
#
# Устанавливается как ~deploy/deploy-staging-dispatch.sh, chmod 700.
#
# Принимает единственный буквальный паттерн: `./deploy-staging.sh <branch>`.
# Имя ветки — единственный переменный вход; секреты (STAGING_BOT_TOKEN и
# т.п.) сюда никогда не приходят — deploy-staging-run.sh читает их из
# локального файла на сервере (см. его docstring). Именно попытка
# протащить `export STAGING_BOT_TOKEN=...` доп. строкой перед командой (так
# работал старый inline-скрипт через appleboy/ssh-action `envs:`) ломала
# буквальный паттерн и отклонялась целиком — та самая причина issue #169.
cmd="${SSH_ORIGINAL_COMMAND:-}"

if [[ "$cmd" =~ ^\./deploy-staging\.sh\ ([A-Za-z0-9_][A-Za-z0-9._/-]*)$ && "$cmd" != *..* ]]; then
    branch="${BASH_REMATCH[1]}"
    exec "$HOME/deploy-staging-run.sh" "$branch"
fi

echo "deploy-staging-dispatch: rejected command: $cmd" >&2
exit 1
