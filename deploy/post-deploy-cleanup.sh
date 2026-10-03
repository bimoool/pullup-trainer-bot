#!/usr/bin/env bash
# Safe post-deploy Docker cleanup. Живёт на VPS как /usr/local/bin/post-deploy-cleanup.sh
# (root:root 755) и вызывается ПОСЛЕДНЕЙ строкой deploy-run.sh / deploy-staging-run.sh (см.
# docs/RESOURCE_LIFECYCLE.md). Копия в репозитории — для ревью; на сервер ставится вручную.
#
# Гарантии:
#   * НИКОГДА не трогает volumes (pgdata/redisdata/…): нет `volume prune`, нет `--volumes`.
#   * Только dangling-образы (не `-a`) — образы, которые использует хоть один контейнер
#     (прод, staging, соседние проекты), не удаляются, даже остановленный контейнер держит образ.
#   * BuildKit-кэш — только старше CACHE_AGE (по умолчанию 168h = 7 суток), так что кэш
#     свежих сборок остаётся и следующий деплой не пересобирает всё с нуля.
#   * Контейнеры не удаляются (на этом VPS живут чужие проекты).
#   * Любая ошибка очистки НЕ валит успешный деплой: скрипт всегда exit 0.
set -uo pipefail

CACHE_AGE="${CACHE_AGE:-168h}"
disk_used_kb() { df -Pk / | awk 'NR==2{print $3}'; }

before=$(disk_used_kb)
echo "== post-deploy cleanup (disk used before: $((before / 1024)) MB)"

docker image prune -f 2>&1 | tail -1 || echo "  image prune failed (ignored)"
docker builder prune -f --filter "until=${CACHE_AGE}" 2>&1 | tail -1 || echo "  builder prune failed (ignored)"

after=$(disk_used_kb)
echo "== reclaimed: $(((before - after) / 1024)) MB; disk now: $(df -h / | awk 'NR==2{print $5" used, "$4" free"}')"
exit 0
