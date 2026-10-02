#!/usr/bin/env bash
# Server-side, READ-ONLY resource report. Живёт на VPS как /usr/local/bin/vps-resource-report.sh,
# запускается systemd-таймером (deploy/systemd/) раз в 6 часов и вручную после деплоя.
# Ничего не удаляет и не принимает аргументов; не требует расширения прав SSH-ключей GitHub Actions.
#
# Пороги (docs/RESOURCE_LIFECYCLE.md): диск WARN>=75% CRIT>=85%; RAM WARN при >=85% used.
# Exit code: 0 OK, 1 WARN, 2 CRIT — systemd помечает unit failed, `systemctl --failed` / journal
# показывают проблему без какого-либо исходящего доступа. Отчёт также пишется в
# /var/lib/resource-report/latest.txt (читаемо пользователем deploy).
set -uo pipefail

OUT_DIR="${OUT_DIR:-/var/lib/resource-report}"
mkdir -p "$OUT_DIR" 2>/dev/null || OUT_DIR="${HOME:-/tmp}"
level=0
bump() { [ "$1" -gt "$level" ] && level=$1; }
section() { printf '\n== %s\n' "$1"; }

{
  echo "resource report $(date -u +%FT%TZ) host=$(hostname)"

  section "disk"
  df -hP / | awk 'NR==1||NR==2'
  pct=$(df -P / | awk 'NR==2{gsub("%","",$5); print $5}')
  if   [ "$pct" -ge 85 ]; then echo "DISK CRITICAL: ${pct}%"; bump 2
  elif [ "$pct" -ge 75 ]; then echo "DISK WARN: ${pct}%"; bump 1
  else echo "disk ok: ${pct}%"; fi
  df -i / | awk 'NR==2{print "inodes used: "$5}'

  section "memory"
  free -m
  mem_pct=$(free | awk '/^Mem:/{printf "%d", ($3/$2)*100}')
  # «Sustained» = два отчёта подряд: единичный пик не считаем (предыдущий уровень хранится в файле).
  mem_pct=${mem_pct:-0}
  prev=$(cat "$OUT_DIR/.mem_prev" 2>/dev/null || echo 0)
  echo "$mem_pct" > "$OUT_DIR/.mem_prev" 2>/dev/null
  if [ "$mem_pct" -ge 85 ] && [ "$prev" -ge 85 ]; then echo "RAM WARN (sustained): ${mem_pct}% (prev ${prev}%)"; bump 1
  else echo "ram: ${mem_pct}% (prev ${prev}%)"; fi
  uptime

  if command -v docker >/dev/null 2>&1; then
    section "docker disk (images / containers / volumes / build cache)"
    docker system df 2>&1
    section "docker containers (size) and live memory"
    docker ps -a --size --format 'table {{.Names}}\t{{.Status}}\t{{.Size}}' 2>&1
    docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}' 2>&1
    section "volumes (names only; never modified by this script)"
    docker volume ls --format '{{.Name}}'
    section "container log sizes (json-file)"
    for c in $(docker ps -aq 2>/dev/null); do
      lp=$(docker inspect --format '{{.LogPath}}' "$c" 2>/dev/null)
      name=$(docker inspect --format '{{.Name}}' "$c" 2>/dev/null)
      if [ -n "$lp" ] && [ -r "$lp" ]; then
        printf '%10s  %s\n' "$(du -h "$lp" | cut -f1)" "$name"
      else
        printf '%10s  %s\n' "n/a" "$name (log not readable by this user)"
      fi
    done
    section "log-rotation check"
    for c in $(docker ps -q 2>/dev/null); do
      cfg=$(docker inspect --format '{{.HostConfig.LogConfig.Config}}' "$c" 2>/dev/null)
      [ "$cfg" = "map[]" ] && { echo "UNBOUNDED logs: $(docker inspect --format '{{.Name}}' "$c")"; bump 1; }
    done
  fi

  section "journald"
  journalctl --disk-usage 2>&1 || true

  section "verdict"
  case $level in 0) echo OK;; 1) echo WARN;; 2) echo CRITICAL;; esac
} > "$OUT_DIR/latest.txt" 2>&1

cat "$OUT_DIR/latest.txt"
logger -t vps-resource-report "level=$level disk=${pct:-?}% mem=${mem_pct:-?}%" 2>/dev/null || true
exit "$level"
