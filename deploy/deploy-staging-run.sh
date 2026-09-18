#!/usr/bin/env bash
set -euo pipefail

# Копия скрипта, живущего на VPS как ~deploy/deploy-staging-run.sh
# (владелец deploy:deploy, chmod 700, запускается от пользователя deploy
# НАПРЯМУЮ, без sudo/root — в отличие от deploy-run.sh рядом: staging-чекаут
# (~/pullup-trainer-bot-staging) и так принадлежит deploy, тому же
# пользователю, что держит ограниченный SSH-ключ, эскалация до root не
# нужна). Вызывается из deploy-staging-dispatch.sh (см. соседний файл — та
# же роль, что у deploy-dispatch.sh для прода, но для ОТДЕЛЬНОГО ключа, не
# трогающего production-ограничение, issue #169). Не деплоится
# автоматически (тот же принцип, что и у deploy-run.sh, см. CLAUDE.md) —
# версионируется здесь для истории и ревью, применяется на сервере вручную.
#
# Второй, независимый слой валидации: повторяет проверку имени ветки здесь
# же, не полагаясь только на regex в dispatch-обёртке.
if [[ $# -ne 1 || ! "$1" =~ ^[A-Za-z0-9_][A-Za-z0-9._/-]*$ || "$1" == *..* ]]; then
    echo "deploy-staging-run: expected a single branch name, got: $*" >&2
    exit 1
fi

branch="$1"
repo_dir="$HOME/pullup-trainer-bot-staging"
secrets_file="$HOME/.staging-secrets.env"

# Секреты (STAGING_BOT_TOKEN/STAGING_CLONE_TOKEN) никогда не приходят через
# SSH-команду — под ограниченным command= в authorized_keys любой аргумент
# помимо имени ветки ломает буквальный паттерн и отклоняется целиком целой
# командой (issue #169: строка `export STAGING_BOT_TOKEN=...`, которую
# appleboy/ssh-action подставлял перед скриптом через параметр `envs:`, и
# была причиной исходного бага — "rejected command" на первой же строке).
# Вместо этого читаются из локального файла на сервере, тем же принципом,
# что ROBOKASSA_*/остальные прод-секреты читаются из .env на сервере, не
# прокидываются через CI на каждый прогон (см. CLAUDE.md, шапка про
# ROBOKASSA_*). Заводится вручную один раз:
#   printf 'STAGING_BOT_TOKEN=...\nSTAGING_CLONE_TOKEN=...\n' > ~/.staging-secrets.env
#   chmod 600 ~/.staging-secrets.env
if [[ ! -f "$secrets_file" ]]; then
    echo "deploy-staging-run: missing $secrets_file (STAGING_BOT_TOKEN/STAGING_CLONE_TOKEN)" >&2
    exit 1
fi
# shellcheck disable=SC1090
source "$secrets_file"

if [[ ! -d "$repo_dir" ]]; then
    git clone --quiet "https://x-access-token:${STAGING_CLONE_TOKEN}@github.com/bimoool/pullup-trainer-bot.git" "$repo_dir"
fi

cd "$repo_dir"
git remote set-url origin "https://x-access-token:${STAGING_CLONE_TOKEN}@github.com/bimoool/pullup-trainer-bot.git"
git fetch --quiet origin
# checkout ИМЕНИ ВЕТКИ (не SHA, как в проде) — staging всегда следует за
# HEAD ветки на момент запуска; ff-only pull страхует от молчаливого
# расхождения с force-push в ветку между fetch и checkout.
git checkout --quiet "$branch"
git pull --quiet --ff-only origin "$branch"

umask 077
cat > .env <<EOF
BOT_TOKEN=${STAGING_BOT_TOKEN}
POSTGRES_USER=pullup_staging
POSTGRES_PASSWORD=pullup_staging
POSTGRES_DB=pullup_staging
DATABASE_URL=postgresql+asyncpg://pullup_staging:pullup_staging@db:5432/pullup_staging
REDIS_URL=redis://redis:6379/0
LOG_LEVEL=INFO
ADMIN_IDS=
MINI_APP_URL=https://staging.app.bimoool.com
MINI_APP_PORT=8002
EOF

# Тот же порядок build → migrate → up, что deploy-run.sh уже использует для
# прода (комментарий там же объясняет причину: применить миграции ДО
# переключения трафика на новые контейнеры, реальный инцидент 2026-09-04)
# — исходный staging-workflow (issue #169) делал `up -d --build`, затем
# опрашивал уже поднятый контейнер на предмет миграции; здесь это
# исправлено заодно, не только сама проблема с deploy-dispatch.
docker compose -p pullup-staging build app web
docker compose -p pullup-staging run --rm app alembic upgrade head
docker compose -p pullup-staging up -d

sleep 5
curl -sf "http://127.0.0.1:8002/health" || (echo "deploy-staging-run: health check failed" && exit 1)
