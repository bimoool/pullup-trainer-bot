#!/bin/bash
# Re-run the whole C-existing audit from S0 (restores snapshot, then runs specs in dependency order).
set -u
cd /home/user/pullup-trainer-bot
./scripts/audit/c_reset.sh
cd webapp-frontend/e2e
for spec in "j1.spec.ts" "j5.spec.ts" "j5b.spec.ts" "j6.spec.ts" "j7.spec.ts" "j8.spec.ts"; do
  [ -f audit/C-existing/$spec ] || continue
  pkill -9 chrome 2>/dev/null
  timeout 600 npx playwright test -c audit/C-existing/playwright.audit.config.ts $spec --reporter=line > /tmp/pw-$spec.out 2>&1
  tail -3 /tmp/pw-$spec.out
done
