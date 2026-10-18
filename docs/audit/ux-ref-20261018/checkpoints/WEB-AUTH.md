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


## CP2 / FINAL — frontend, bot tests, E2E, mutation checks
- Time: 2026-10-18 ~19:10 UTC. Active ~75 min since CP1, waiting ~12 min (stack seeding ~5 min, pytest/vite), rework: 1 test-helper fix
  (`_approve` asserted open on a second call), 1 config change (IP limits made settings so a single-IP E2E stack is not rate-limited), seed loop widened to n=0..8 so
  spec constants satisfy `test_spec_telegram_ids_are_seeded`.
- Summary: bot deep-link login (device-code) complete. Backend `app/services/web_login.py` + `app/web/web_auth.py` (+ `register_web_auth(app)` in main.py);
  `get_validated_init_data` accepts sentinel `web-session` only with a valid cookie (real initData path unchanged; direct-call tests unchanged);
  bot handler `app/bot/handlers/web_login.py` (before `start_router`; telegram_id from `callback.from_user`); frontend `platform/{authBootstrap,LoginScreen,session,webAuthApi,webAuthLogic,SignOutButton}`;
  Mini App precedence preserved (initData -> `telegram`, `/api/web-auth/*` never called, tested).
- New settings (all optional): `BOT_USERNAME`, `WEB_AUTH_COOKIE_SECURE` (default true), `WEB_AUTH_TRUSTED_PROXY` (use X-Real-IP; nginx conf already sets it; set true in prod `.env` or all users share the proxy IP prefix),
  `WEB_AUTH_IP_REQUEST_LIMIT/POLL_LIMIT/BAD_POLL_LIMIT`, `WEB_AUTH_TEST_LOGIN` (+ requires `BOT_TOKEN=e2e-test-token`).
- **Production notes (coordinator/owner, not done by me):** set `BOT_USERNAME` (or rely on getMe), `WEB_AUTH_TRUSTED_PROXY=1` behind nginx; the migration `c7e2a9d4b1f8` adds two new tables only
  (no `*_archive_admin_reset` impact). Cookie is `Secure` by default so production must be https (it is).
- Files: app/{config.py, db/models.py, db/migrations/versions/c7e2a9d4b1f8_web_auth_tables.py, services/web_login.py, web/{web_auth.py,auth.py,main.py}, bot/{handlers/web_login.py,handlers/__init__.py,texts.py}};
  scripts/{e2e_web_login.py,e2e_seed_all.sh}; tests/{conftest.py (TABLES += web_login_requests), test_web/test_web_auth.py, test_bot/test_web_login.py};
  webapp-frontend/src/platform/{authBootstrap.ts,LoginScreen.tsx,login.css,session.ts,webAuthApi.ts,webAuthLogic.ts,SignOutButton.tsx}, tests/{webAuthLogic,webAuthSession}.test.ts,
  e2e/{fixtures/webAuth.ts,scenarios/web/auth-login.spec.ts,scenarios/web/auth-miniapp.spec.ts}; this file and `WEB-AUTH-seam-request.md`.
- Tests added: pytest 43 (`test_web_auth.py`) + 8 (`test_web_login.py`); node 6 (`webAuthLogic`, `webAuthSession`); Playwright 9 specs x 2 projects (web-desktop, web-mobile) = 18, all green on my stack (8081).
  Names cover: expiry, single use, wrong/missing secret identical 404, only opener may approve, double approve, deny, per-request lockout, per-IP limits, cookie flags (HttpOnly/Secure/SameSite=Lax/Path),
  logout revocation + replay, logout needs custom header (CSRF), no CORS, idle (14d) / absolute (30d) expiry, deleted user, sentinel without/with garbage cookie, forged initData with cookie,
  no token/secret in logs/body/URL/storage, test-login absent by default and gated by both conditions (also re-checked per request, and not present in deploy files).
- **Mutation proof (tests fail without the fix):** (1) handler using `callback.message.from_user.id` -> `test_confirm_uses_the_presser_not_the_message_author` + `test_double_confirm...` fail;
  (2) consume without `status='approved'` guard -> `test_single_use` fails; (3) sentinel accepted without cookie -> 7 tests fail (`test_sentinel_without_cookie_is_401`, `test_deleted_user_session_is_rejected`, ...). Each reverted.
- Threat model additions: session tokens/secrets only as SHA-256 in DB; token never in body/URL/storage; compare via `hmac.compare_digest`; all status moves are atomic conditional UPDATEs.
  Known limits: (a) rotation of the session token only happens at login (no mid-session rotation: a rotation would race parallel tabs; sessions are revocable and capped at 30 days);
  (b) in-memory per-IP limiters are per process (single uvicorn in compose); DB-backed per-IP creation limit is shared; (c) no user "blocked" flag exists in `users` — blocking == deleting the user or `logout-all`;
  (d) a victim who blindly confirms a relayed link authorises the attacker's browser (device-code phishing): mitigated by code in both places, bot warning text, 5 min TTL, cancel button, first-opener binding — not eliminable without Login Widget domain binding.
- Seam requests: `WEB-AUTH-seam-request.md` — (1) place `<SignOutButton />` (Settings/profile or shell), (2) browser-mode text/button for session-expired in App.tsx error block.
- Open risks: not exercised with a real Telegram client/`getMe` (no network; link path covered via the `/start weblogin_<id>` fallback in E2E, the `bot_link` branch by pytest `test_create_returns_code_secret_and_link...`);
  the offline IndexedDB queue is not user-keyed (pre-existing, documented above).
- Verify (coordinator): from the worktree, venv at `/Users/kirillv./Documents/Claude Code/.venv-ux312/bin`:
  `BOT_TOKEN=x DATABASE_URL=postgresql+asyncpg://x:x@localhost/x pytest tests/test_web/test_web_auth.py tests/test_bot/test_web_login.py tests/test_web/test_auth.py tests/test_web/test_qa_mint_init_data.py tests/test_web/test_session_commit_scope.py tests/test_scripts -q`;
  `ruff check app/ tests/`; `alembic heads` (one: c7e2a9d4b1f8); `cd webapp-frontend && node --test tests/*.test.ts && npx tsc -b && npx vite build`;
  E2E: `WEB_AUTH_COOKIE_SECURE=0 WEB_AUTH_TEST_LOGIN=1 WEB_AUTH_IP_REQUEST_LIMIT=1000 WEB_AUTH_IP_POLL_LIMIT=100000 WEB_AUTH_IP_BAD_POLL_LIMIT=100000 bash /tmp/ux_stack.sh <wt> 8081 web_auth`, then in `webapp-frontend/e2e`:
  `BOT_TOKEN=e2e-test-token PYTHON=<venv>/python DATABASE_URL=<stack db url> POSTGRES_*=... E2E_BASE_URL=http://127.0.0.1:8081 CI=1 WEB_AUTH_TEST_LOGIN=1 npx playwright test scenarios/web/auth-login.spec.ts scenarios/web/auth-miniapp.spec.ts --project=web-desktop --project=web-mobile`.
  Specs need `PYTHON`, `DATABASE_URL` (they shell out to `scripts/e2e_web_login.py`) and the stack flags above.

- Existing tests changed (minimally, intended behaviour change = one new alembic head): `tests/test_scripts/test_course_prescription_migration.py::test_e_single_head_follows_training_session_v2`
  and `tests/test_scripts/test_single_history_migration.py` (`CHAIN_HEAD`) pinned the head to `b5d8e1f3a6c9`; they now expect `c7e2a9d4b1f8` whose parent is `b5d8e1f3a6c9` (chain assertions kept). Both pass.
- Not clean on this macOS box and unrelated to this work: `tests/test_scripts/test_deploy_*_guarded.py` fail in preflight (`free memory:` empty — Linux `free`/meminfo missing); the full `tests/test_scripts` run is very slow here (migration scratch DBs), so I ran only the head-pinning files + `test_e2e_seed_integrity.py` (green).
- Final verification run on branch: ruff clean; `tests/test_web/test_web_auth.py` + `tests/test_bot/test_web_login.py` + auth/qa_mint/commit_scope/hello = 76 passed; node unit 376 passed; `tsc -b && vite build` clean; Playwright web-desktop+web-mobile auth specs 18/18, `home-discovery` + `not-onboarded` (chromium) 4/4.
- Stack on :8081 stopped, `docker compose down` done.
