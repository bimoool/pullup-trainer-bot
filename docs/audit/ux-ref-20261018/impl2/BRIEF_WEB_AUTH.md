RUN MODE: LOCAL CODE
MODEL: STANDARD / SONNET
MODEL REASON: security-sensitive but fully specified flow on top of existing auth dependency and bot; the scheme is pre-chosen by the coordinator
SESSION: NEW
TASK TYPE: IMPLEMENTATION
BASE SHA: the seam commit on `campaign/ux-ref-20261018` (given in your launch message); code base main e2ed40e
BRANCH / WORKTREE: `web/auth` / `/Users/kirillv./Documents/Claude Code/pullup-web-auth`
ACCESS: git, Docker, venv, npm. No real Telegram client; the bot is exercised through aiogram's `Dispatcher.feed_update` stub session (`tests/test_bot/conftest.py`). Unverified: BotFather domain settings (not needed by the chosen scheme).
DELIVERABLE: pushed branch: backend + bot handler + frontend login + tests + E2E spec; checkpoint file `checkpoints/WEB-AUTH.md` with the threat model
TIMEBOX: first checkpoint ≤ 15 min (dependency audit + scheme + test-login helper plan); CP1 with the test-login helper pushed within ~40 min so WEB-LAYOUT can rebase; then continue to the end
NEXT STATUS: first checkpoint pushed within 15 min
AUTHORIZED ACTIONS: edit owned files, add one Alembic migration (new tables only), run focused tests, commit, push own branch. No merge, no deploy.

# Task WEB-AUTH — sign in from a plain browser with Telegram, protected browser session, same account

## Chosen scheme (do not redesign; challenge only with evidence)
**Bot deep-link login (device-code style), no BotFather domain setting required.** Telegram Login Widget is NOT used (needs `/setdomain`, an owner action) — keep it as a documented alternative in the checkpoint file.
1. Browser (no Telegram initData, no valid session) shows «Войти через Telegram». `POST /api/web-auth/login-requests` → server creates a request: `request_id` (128-bit random, public), `browser_secret` (256-bit random, returned **only** to that browser in the response body; server stores only its SHA-256), a **4-digit confirmation code**, `expires_at = now+5 min`, status `pending`. Rate-limited per IP.
2. The page shows the code and a button/link `https://t.me/<bot_username>?start=weblogin_<request_id>` (bot username from settings/getMe) and polls `POST /api/web-auth/login-requests/{id}/poll` with the browser_secret (header `X-Web-Login-Secret`).
3. In Telegram the bot receives `/start weblogin_<request_id>`: replies «Вход в браузере. Код на экране: 4821. Подтверждайте, только если сами открыли сайт» with inline [Подтвердить] [Отмена]. Confirm binds `telegram_id` (the callback's `from_user.id` — **CLAUDE.md rule: never `message.from_user`**) to the request, status `approved`. Only an **existing, onboarded-or-not user record keyed by telegram_id is reused; never create a second account** (get-or-create exactly as the Mini App's `hello` flow does — reuse that code path).
4. The next poll (valid secret, not expired, approved, single use) atomically consumes the request and sets the session cookie: random 256-bit token, stored as SHA-256 in `web_sessions(id, user_id, token_hash, created_at, last_seen_at, expires_at, revoked_at, user_agent_hash, ip_prefix)`; cookie `pullup_web_session` **HttpOnly, Secure (configurable off for local http), SameSite=Lax, Path=/**, idle expiry 14 days, absolute 30 days, rotation on privilege-relevant events.
5. Authenticated requests: the frontend keeps sending the existing header `X-Telegram-Init-Data` with the **sentinel value `web-session`**; `get_validated_init_data` (app/web/auth.py) accepts the sentinel **only together with a valid session cookie** and returns an `InitData`-compatible object with `user.id/first_name/...` from the stored user — **all existing routes and the frontend API helpers stay unchanged**. A real Telegram initData is still validated exactly as before; a sentinel without a valid cookie → 401. CSRF: the custom header cannot be set cross-site without CORS (none configured) — add a test that proves a request without the header is rejected and that no permissive CORS exists.
6. `GET /api/web-auth/session` (who am I / is there a session), `POST /api/web-auth/logout` (revokes the session, clears the cookie), `POST /api/web-auth/logout-all` optional.
7. Mini App unaffected: inside Telegram `resolveAuth()` still returns `telegram` first; browser login is attempted only when there is no initData.

## Dependency audit (checkpoint 1, ≤ 15 min)
List every place that depends on Telegram initData or the Telegram SDK for **identity/authorisation** (`app/web/auth.py` and its users, `init_data.user.*` fields read by routes, bot-only flows such as subscription confirmation, `webapp-frontend/src/platform/authBootstrap.ts`, `api.ts`/`apiV2.ts` header helpers, offline queue / engine reconciliation that stores `initDataRaw`, anything that stores initData in IndexedDB/localStorage). Record what is affected by the sentinel approach and how you handle it.

## Security requirements (each needs a test)
Request expiry; single use; wrong/missing secret → 404/401 without leaking existence; approved only by the bot callback of the matching Telegram user id; cannot approve twice; deny/cancel marks the request; poll after expiry; brute-force limits (per IP and per request); session cookie flags; session revocation on logout; sessions of **deleted/blocked** users rejected; no token in URLs/logs/localStorage; no initData/secret in server logs; the confirmation text carries the code; expired sessions give the existing «сессия истекла» UX path (see `sessionErrors.ts`); idle/absolute expiry. A **phishing note** in the threat model (device-code relay) and the mitigations (code shown on both screens, short TTL, text warning).

## Test-only login (needed by E2E and by WEB-LAYOUT) — strictly gated
`POST /api/web-auth/test-login {telegram_id}` exists **only** when `WEB_AUTH_TEST_LOGIN=1` **and** `BOT_TOKEN == "e2e-test-token"` (checked at request time and registered conditionally); otherwise the route does not exist (404). Never enabled in `docker-compose*.yml`/deploy files. Test that it is absent by default. Push this helper as an early checkpoint (CP1) and tell the coordinator in the checkpoint file so WEB-LAYOUT can rebase.

## Frontend
`platform/authBootstrap.ts::resolveAuth()`: Telegram initData → `telegram`; else `GET /api/web-auth/session` → `browser` (initDataRaw = `"web-session"`) or `login`. `platform/LoginScreen.tsx`: Russian copy, code display, deep-link button, polling with backoff, cancel, error states (expired → «Запросить новый код»), accessible. `platform/session.ts::signOutBrowser()` calls logout then reloads. You do **not** edit `App.tsx`; if you need a change there, write a seam request.

## Acceptance
Backend + bot + frontend unit tests; E2E `scenarios/web/auth-*.spec.ts` (projects web-desktop/web-mobile): login via the bot stub path (the spec drives the bot confirmation by calling the same service function the handler uses, or feeds a Telegram update through the real dispatcher in a Python helper), same user as the Mini App (same plan/history visible), reload keeps the session, logout, expired request, wrong code, no duplicate user row (`SELECT count(*) FROM users WHERE telegram_id=…` stays 1). Mini App specs for the same seeded user still green. `ruff`, `tsc`, `vite build`, single alembic head.
