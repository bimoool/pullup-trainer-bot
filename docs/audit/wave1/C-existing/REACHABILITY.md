# REACHABILITY — C-existing slice (✅ ok / ❌ F-id / ⛔ BLOCKED BY / ? untested)

| Node | audit_existing_active | audit_legacy_existing | audit_returning_week_transition | trial / rested | active_paid | expired (a / b) |
|---|---|---|---|---|---|---|
| Open app (existing user, no onboarding re-ask) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Главная: program card «В плане» | ✅ (❌ F-C-20 raw `pull_ups`) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Планы: current-week actionable workout | ✅ | ✅ | ✅ (week auto-created) | ❌ F-C-19 (trial, 1 d) / ✅ rested | ✅ | ✅ banner only ❌ F-C-02 |
| Pre-start screen target == Live target | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ F-C-03 |
| Live: log ≥2 sets, Finish, summary | ✅ | ✅ | ✅ | ✅ (rested) | ✅ | ✅ but should be gated ❌ F-C-02 |
| Reload keeps result (Планы 1 из 3, Журнал) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Аналитика reflects the new session | ✅ (❌ F-C-20 labels) | ✅ | ✅ | ? | ? | ? |
| Paywall for expired | – | – | – | – | – | ❌ F-C-02 / F-C-18 |
| Admin grant (bot handler, feed_update) expired -> active, state kept | – | – | – | – | – | ✅ (a: plan 1/3 + Журнал unchanged; b: then trains ✅) |
| Journal: open native plan session | ✅ | – | – | – | – | – |
| Journal: edit / clone / delete native plan session | ❌ F-C-05 | – | – | – | – | – |
| Journal: backdate activity («Другую активность») + reload | ✅ | – | – | – | – | – |
| Journal: edit activity rating/comment + reload | ✅ (❌ F-C-08 no duration) | – | – | – | – | – |
| Journal: clone activity | ❌ F-C-09 | – | – | – | – | – |
| Journal: delete activity + reload + Аналитика −1 | ✅ | – | – | – | – | – |
| Journal: backdate pull-up workout («Тренировку из моих» needs Builder workout) | ⛔ no pull-up backdate path for plan program (not pursued; BackdateForm legacy screen UNTESTED) | – | – | – | – | – |
| Legacy workout: edit values + reload | – | ✅ | – | – | – | – |
| Legacy workout: delete + Аналитика updates | – | ❌ F-C-14 | – | – | – | – |
| Backfilled elective visible in Журнал | – | ✅ (❌ F-C-16 sets) | – | – | – | – |
| J7 reopen (new context) mid-Live, finish, plan/journal persist | audit_persist ✅ (❌ F-C-15 minor) | | | | | |
| J8 reload mid-Live resume | audit_interrupt ✅ | | | | | |
| J8 browser Back during Live | ✅ (leaves to about:blank in the harness; reopening resumes) | | | | | |
| J8 offline set submit + reconnect sync | ✅ ("Нет сети — подходы сохраняются локально…", 2 set_logs after reconnect) | | | | | |
| J8 double-tap Finish -> 1 session | ✅ | | | | | |
| Telegram native BackButton in Live | ? untested (mock without backButton option) | | | | | |
| Dark theme pass | ? not run (B-role scope) | | | | | |
