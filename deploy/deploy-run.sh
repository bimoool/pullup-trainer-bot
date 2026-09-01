#!/usr/bin/env bash
set -euo pipefail

# Копия скрипта, живущего на VPS как /usr/local/bin/deploy-run.sh
# (владелец root:root, chmod 700, запускается от root только через sudo
# из /usr/local/bin/deploy-dispatch.sh — см. issue #14 для полного
# комплекта authorized_keys/dispatch-скрипта/sudoers). Не деплоится
# автоматически (см. CLAUDE.md: деплой-образ не содержит .git/git/gh, а
# сам этот файл — не часть образа) — версионируется здесь для истории и
# ревью, применяется на сервере вручную.
#
# Второй, независимый слой валидации: этот скрипт разрешён в sudoers для
# пользователя deploy с любым аргументом (sudoers не умеет проверять формат
# аргумента сам), поэтому повторяет проверку SHA здесь же, уже под root —
# deploy-dispatch.sh не единственная линия обороны.
if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
    echo "deploy-run: expected exactly one 40-char hex sha, got: $*" >&2
    exit 1
fi

sha="$1"
repo_dir="/root/pullup-trainer-bot"

cd "$repo_dir"
git fetch --quiet origin
# Именно checkout конкретного SHA, не `git pull`/`git merge` на floating main —
# деплоится ровно тот коммит, что был на GitHub в момент workflow_dispatch.
git checkout --quiet "$sha"
# Оба сервиса, собираемые из этого репозитория (docker-compose.yml): app —
# бот, web — Mini App (issue #15/PR #16). db/redis — сторонние образы, их
# не нужно пересобирать при каждом деплое.
docker compose build app web
docker compose up -d app web
