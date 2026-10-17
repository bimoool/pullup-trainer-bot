#!/usr/bin/env bash
# Однократная настройка доступа GitHub Actions к guarded-выкату production. Запускается владельцем от root на VPS
# (например, из веб-консоли DigitalOcean) одной командой, скрипт берётся из проверенного коммита:
#
#   git -C /root/pullup-trainer-bot fetch -q origin <SHA> && \
#     git -C /root/pullup-trainer-bot show <SHA>:deploy/install-prod-actions-access.sh | bash -s -- <SHA>
#
# Что делает (и только это):
#   1. ставит в /root/bin из коммита <SHA>: deploy-production-guarded-run.sh, rollback-production-guarded.sh,
#      prod-guarded-dispatch.sh (печатает sha256 каждого; рабочее дерево прода не трогает — только `git show`);
#   2. создаёт НОВЫЙ ключ ed25519 и добавляет в /root/.ssh/authorized_keys одну строку
#      restrict,command="/root/bin/prod-guarded-dispatch.sh" … gh-actions-prod-guarded
#      (прежняя строка с тем же комментарием заменяется; остальные строки, в т.ч. ключи deploy.yml, не меняются);
#   3. печатает приватный ключ ОДИН раз и удаляет его с сервера — его нужно сохранить в секрет репозитория
#      PROD_GUARDED_SSH_KEY (Settings → Secrets and variables → Actions). Повторный запуск выпускает новый ключ
#      и отзывает старый.
# Ничего не останавливает, не собирает и не деплоит.
set -euo pipefail

SHA="${1:-}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "usage: … | bash -s -- <40-hex-sha>" >&2; exit 2; }
[ "$(id -u)" = "0" ] || { echo "run as root" >&2; exit 2; }
REPO=/root/pullup-trainer-bot
BIN=/root/bin
COMMENT=gh-actions-prod-guarded
AUTH=/root/.ssh/authorized_keys

for tool in git flock ssh-keygen sha256sum install; do command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 1; }; done
git -C "$REPO" cat-file -e "${SHA}^{commit}" || { echo "commit $SHA not found in $REPO (fetch it first)" >&2; exit 1; }

mkdir -p "$BIN" /root/backups && chmod 700 "$BIN" /root/backups
echo "== scripts from $SHA"
for f in deploy-production-guarded-run.sh rollback-production-guarded.sh prod-guarded-dispatch.sh; do
  git -C "$REPO" show "$SHA:deploy/$f" > "$BIN/$f.new"
  bash -n "$BIN/$f.new"
  install -m 700 "$BIN/$f.new" "$BIN/$f" && rm -f "$BIN/$f.new"
  sha256sum "$BIN/$f"
done

echo "== ssh key"
umask 077
mkdir -p /root/.ssh && chmod 700 /root/.ssh && touch "$AUTH" && chmod 600 "$AUTH"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
ssh-keygen -q -t ed25519 -N "" -C "$COMMENT" -f "$TMP/key"
grep -v " ${COMMENT}\$" "$AUTH" > "$TMP/auth" || true
printf 'restrict,command="%s/prod-guarded-dispatch.sh" %s\n' "$BIN" "$(cat "$TMP/key.pub")" >> "$TMP/auth"
cat "$TMP/auth" > "$AUTH"
echo "authorized_keys: $(grep -c " ${COMMENT}\$" "$AUTH") line(s) for $COMMENT, $(wc -l < "$AUTH") total"

prl="$(sshd -T 2>/dev/null | awk '$1=="permitrootlogin"{print $2}')"
case "$prl" in
  yes|prohibit-password|without-password|forced-commands-only) echo "sshd PermitRootLogin=$prl: key login with forced command allowed" ;;
  *) echo "WARNING: sshd PermitRootLogin=${prl:-unknown} — root key login may be refused; nothing was changed in sshd" ;;
esac

echo
echo "== Сохраните ВСЁ между линиями (включая BEGIN/END) в секрет репозитория PROD_GUARDED_SSH_KEY. С сервера ключ удаляется."
echo "-----------------------------------------------------------------------------------------------"
cat "$TMP/key"
echo "-----------------------------------------------------------------------------------------------"
echo "fingerprint: $(ssh-keygen -lf "$TMP/key.pub")"
