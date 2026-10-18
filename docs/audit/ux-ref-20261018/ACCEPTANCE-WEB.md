# Acceptance — browser version + Mini App (candidate 2d3e3a4, deploy pending owner step)

Verified locally on the gated build (E2E, isolated stand with the test bot stub): web-desktop 1280×800 and web-mobile 390×844 specs in `scenarios/web/`.
**Not verified:** Telegram login with the real bot and a real Telegram client (no staging bot token/client on this machine; the bot confirmation is driven through the real aiogram dispatcher with a stub session); WebKit/iOS browsers; a full live workout end to end in the browser; Mini App inside a real Telegram client.

1. Open the site in a plain browser (no Telegram): «Войти через Telegram» → code on screen + button to the bot. In Telegram: the bot shows the same code → «Подтвердить». The browser signs in as the **same account** (same plan, programmes, subscription, history; `users` row count unchanged).
2. Reload keeps the session; «Выйти» (top bar / side nav) ends it; the old cookie no longer works; expired/cancelled/wrong-code requests show clear text.
3. Layout: ≥ 768 px side navigation + centred column; < 768 px bottom navigation; in-page «Назад»; Escape closes sheets; light/dark follows the system; no horizontal overflow 320…1920.
4. Plan editor/schedule (UX-EDITOR): create a 4-week plan with per-workout weekly quantities, totals per week, place sessions on days incl. one workout twice on a day («×2», «все занятия размещены»), move across weeks, remove with confirmation, past days refused («Без дня» always allowed); existing plans and history unchanged until the first edit.
5. Mini App unchanged: open from the bot as before (initData wins; `/api/web-auth/*` not called inside Telegram).
6. Subscription without charging: paywall sheet and «Нужна подписка» rows work in the browser; payment links open in a new tab (`noopener`); nothing is paid in tests.
