# Checkpoint log — WEB-AUTH (sign in from a plain browser)

## CP1 — dependency audit + scheme + TEST-LOGIN HELPER PUSHED (WEB-LAYOUT: rebase on this commit)
- Time: 2026-10-18 ~17:57 UTC (wall clock). Active ~40 min, waiting ~1 min (pytest), rework 0.
- **`POST /api/web-auth/test-login {telegram_id}` is on this branch now** (sets the same cookie `pullup_web_session`, then
  the frontend header `X-Telegram-Init-Data: web-session` works on every existing route). It exists only when
  `WEB_AUTH_TEST_LOGIN=1` **and** `BOT_TOKEN=e2e-test-token` (checked at registration and again on every request,
  otherwise 404). Cookie `Secure` must be switched off for plain http: also set `WEB_AUTH_COOKIE_SECURE=0` in the E2E stack env.
  E2E env addition: `WEB_AUTH_TEST_LOGIN=1 WEB_AUTH_COOKIE_SECURE=0`. Unknown telegram_id is created (as /start does); seeded ids reuse the row.
- Frontend login screen / bootstrap are NOT in CP1 (stubs untouched). WEB-LAYOUT can already call test-login via Playwright
  `request.post('/api/web-auth/test-login', {data:{telegram_id}})` (cookie lands in the context) — but `resolveAuth()` still
  returns `error` in a browser until CP2 wires `GET /api/web-auth/session` (planned next).

### Scheme confirmation
Bot deep-link / device-code exactly as in the brief. Implemented: `app/services/web_login.py` (all state transitions are single conditional
`UPDATE … WHERE status=… RETURNING`), `app/web/web_auth.py` (router, cookie, limiter, test-login), `app/bot/handlers/web_login.py`
(registered **before** `start_router`, `CommandStart(deep_link, magic=args startswith weblogin_)`), tables `web_login_requests`, `web_sessions`
(migration `c7e2a9d4b1f8`, single head). Additions beyond the brief (security): the request is bound to the first Telegram user who opens the
link (`opened_by_telegram_id`); only that user can confirm/cancel; a second user gets «ссылка уже открыта в другом аккаунте».
`first_name` copied from the callback to the session (the `users` table has no first_name; Mini App `hello` takes it from initData).

### Dependency audit (what depends on Telegram initData for identity/authorisation)
1. `app/web/auth.py::get_validated_init_data` — the **only** identity gate; 55 reads of `init_data.user.id`, 1 of `.user.first_name`, nothing else
   (no `auth_date`, `query_id`, `start_param`, `chat`…). So an `InitData`-compatible object with `.user.id/.first_name` is sufficient. Handled:
   sentinel `web-session` + cookie → `WebInitData`; real initData path byte-for-byte unchanged; sentinel without a valid cookie → 401.
   Direct callers (tests call the function directly with only `x_telegram_init_data=`) keep working (the new param is a `Depends` default and is ignored there).
2. Routes depend on `Header X-Telegram-Init-Data` via the shared dependency → unchanged. `get_session` is `scope="function"` in my dependency
   (`test_every_route_commits_before_the_response_is_sent` stays green).
3. Bot-only flows: `/start`, onboarding, subscription (Robokassa/Stars) are keyed by `telegram_id` in the DB, not by initData; browser sessions resolve to the same
   `users` row by `telegram_id`, so subscription status/payments are shared. Payments link generation itself is Mini App/bot UX — not touched, no live calls.
4. Frontend: 11 `api*.ts` helpers put `initDataRaw` into `X-Telegram-Init-Data` — unchanged, `initDataRaw` is `"web-session"` in browser mode.
   `App.tsx` keeps `initDataRaw` in React state only (no storage). `liveEngineClient.ts` / `offlineSession.ts` take it as a parameter; **neither persists it** (verified: no
   initData in IndexedDB/localStorage). The offline query cache `pullup-v2-query-cache` (localStorage, react-query persister) holds **data** of the signed-in user →
   on browser logout `signOutBrowser()` removes that key so the next person on a shared browser doesn't see it. Offline IndexedDB session queue: not user-keyed
   today; documented risk (same as for a Telegram account switch), not changed.
5. `sessionErrors.ts`: SESSION_EXPIRED text mentions Telegram; browser mode needs «Войдите заново» — handled in the login screen (401 on any call → login) without editing `App.tsx`
   (seam request if the 401 handler lives there).
6. `scripts/qa/mint_init_data.py` (staging QA) is unaffected (real HMAC path).
7. Blocked users: the `users` table has no blocked/banned flag → "blocked" can only be implemented as deletion (sessions cascade-delete with the user) or
   `logout-all`; tested for deleted users. If a block flag appears later, add it to `resolve_session`.

### Threat model (summary; details to be extended in the final block)
- Device-code relay phishing: attacker shows victim a link to *their* login request and asks to confirm. Mitigations: 4-digit code shown in the bot message and on the
  attacker's screen is irrelevant to the victim but the bot text says «подтверждайте, только если вы сами открыли сайт и код на экране совпадает»; 5-min TTL;
  single use; first-opener binding; cancel button. Residual risk: a victim who confirms blindly. The Login Widget alternative was **not** used (needs owner's BotFather `/setdomain`);
  documented as alternative: widget gives signed `id/first_name/auth_date/hash` verified with the bot token, no bot round-trip, but needs the domain registered.
- Brute force: 128-bit request id, 256-bit secret, 5 bad secrets lock the request, per-IP creation (10/10 min, DB) and poll (240/min) + bad-poll (30/10 min) limits (in-process).
- CSRF: cookie is SameSite=Lax HttpOnly; state-changing calls need the custom header (no CORS configured, tested); poll uses the secret header.
- XSS: token is HttpOnly, never in JS, URL, storage, logs.

### Tests so far (all green): `tests/test_web/test_web_auth.py` (43), existing auth tests unchanged and green. ruff clean, one alembic head.
### Next
Bot handler tests, frontend (`authBootstrap`, `LoginScreen`, `session.ts`, `webAuthApi.ts`) + unit tests, E2E `auth-*.spec.ts`, seed scenario in 942000–942099, mutation checks.
