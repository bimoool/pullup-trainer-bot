#!/usr/bin/env bash
# ONE-TIME, idempotent installer for the resource tooling. Run ON THE VPS as root:
#   see docs/RESOURCE_LIFECYCLE.md («Owner one-time VPS action»). Safe to re-run.
# Installs: /usr/local/bin/{vps-resource-report,post-deploy-cleanup}.sh, the systemd timer, and the
# post-deploy hook in the two server-side deploy scripts (prod: /usr/local/bin/deploy-run.sh,
# staging: /home/deploy/deploy-staging-run.sh). Backs each edited script up first (*.bak-resource).
# Touches no Docker volume, container, image or database.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for f in vps-resource-report.sh post-deploy-cleanup.sh; do
  install -m 755 -o root -g root "$SRC/$f" "/usr/local/bin/$f"
done
install -d -m 755 -o root -g root /var/lib/resource-report
install -m 644 "$SRC"/systemd/vps-resource-report.service "$SRC"/systemd/vps-resource-report.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now vps-resource-report.timer

HOOK='if [ -x /usr/local/bin/post-deploy-cleanup.sh ]; then /usr/local/bin/post-deploy-cleanup.sh || true; fi'
add_hook() {
  local target="$1"
  if [ ! -f "$target" ]; then echo "SKIP (not found): $target"; return; fi
  if grep -q post-deploy-cleanup "$target"; then echo "hook already present: $target"; return; fi
  if grep -nE '^[[:space:]]*exec[[:space:]]' "$target" >/dev/null; then
    echo "NOT EDITED (script uses exec, hook would never run): $target — add the hook by hand before the exec" >&2
    return
  fi
  cp -p "$target" "$target.bak-resource"
  printf '\n# Safe post-deploy Docker cleanup (docs/RESOURCE_LIFECYCLE.md); never fails the deploy.\n%s\n' "$HOOK" >> "$target"
  echo "hook appended: $target (backup $target.bak-resource)"
}
add_hook /usr/local/bin/deploy-run.sh
add_hook /home/deploy/deploy-staging-run.sh

systemctl start vps-resource-report.service || true   # first report now; exit 1/2 = WARN/CRIT, not an install error
echo "--- first report"; cat /var/lib/resource-report/latest.txt
echo "--- timer"; systemctl list-timers vps-resource-report.timer --no-pager
