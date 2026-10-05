# PROFILES — B-fresh-clean

DB `pullup_audit_b`: `alembic upgrade head` only (revision `9e3f1a4b6c80`), no catalogue script run. Verified read-only at start:
`programs=0, exercises=0, users=0, collections=0 (shipped by migration: 3 assessment_protocols, 1 collections row — see below), complexes=0`.
Server: uvicorn :8091, Redis db 1, viewport 390x844 (iPhone-like, isMobile, touch), light theme (one dark pass for empty states).
Auth: `X-Telegram-Init-Data` HMAC-signed with `BOT_TOKEN=audit-token` via `window.Telegram.WebApp.initData` (same mechanism as `fixtures/initData.ts`, `fixtures/telegramMock.ts`).

## audit_fresh_active  (tg 7100001 exploration, 7100011 J1, 7100014 J4)
Created ONLY through the UI: open Mini App -> baseline "Замер" (reps) -> "Да" -> "Продолжить" -> questionnaire 5 steps (вес, рост, пол, дата рождения, часовой пояс) -> "Готово".
**UI onboarding was possible; no injection used.** Onboarding start the 14-day trial (users.subscription_status=trial, subscriptions row source=trial).

| Entity | Class | How |
|---|---|---|
| users row (telegram_id, name "Audit") | AUTH NECESSITY | created by first authenticated request /api/hello |
| baseline (8 reps) | DOMAIN NECESSITY | UI onboarding POST /api/onboarding/baseline |
| questionnaire (78 kg, 180 cm, male, 1992-04-15, Europe/Moscow) | DOMAIN NECESSITY | UI POST /api/onboarding/questionnaire |
| subscription trial (14 days) + coins 50 + achievement "Первый замер" | DOMAIN NECESSITY (side effects of onboarding, not set by me) | server-side |
| assessment_protocols (3) / collections (1) rows | SYSTEM CONTENT (shipped by migrations, present before any user) | alembic |
| active plan / plan items / personal workouts / exercises / sessions / journal / analytics / assessments | ABSENT at S0 (verified) | — |

Entities created later *by journeys through the UI* (not S0): workouts, exercises ("Подтягивания", "Тяга"), plan rows, sessions — all created by UI taps (see TRACE.md). No TEST CONVENIENCE entity exists in any fresh-user journey.

## audit_empty_library  (tg 7100012 J2/J3/J7, 7100016 light + 7100017 dark empty states)
Same creation as above. On this DB the library is empty by construction (exercises=0, programs=0, workouts=0).
No injection.

## audit_fresh_expired  (tg 7100015 spec; 7100003 exploration)
1. Fresh onboarding through the UI exactly as audit_fresh_active (trial, 14 days).
2. **TEST HARNESS INJECTION / DOMAIN NECESSITY** (no real user can fast-forward a trial): 
   `UPDATE users SET subscription_expires_at = now() - interval '1 day' WHERE telegram_id = 7100015;`
   `SubscriptionService.refresh_status` (app/services/subscription.py:89) then lazily flips the cached `users.subscription_status` to `expired` on the next access check.
   Note: updating only the `subscriptions` table is NOT enough (the app reads the `users` cache columns; my first attempt with `subscriptions` only left the Profile saying "пробный период (осталось 14 дн.)").
Never counts as a PASS of the upstream onboarding path (which was exercised on a separate user without injection).

## Not injected (explicitly)
`OnboardingService.record_baseline_and_start` / `complete_questionnaire_and_start_trial` were NOT used: the UI path works.
No catalogue content injected.
