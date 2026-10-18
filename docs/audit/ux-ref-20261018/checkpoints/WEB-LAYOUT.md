# WEB-LAYOUT checkpoints

## Checkpoint 1 — inventory + design (UTC 2026-10-18, design only, no code)
Active min: ~12, waiting: 0, rework: 0.

### SDK / Telegram coupling inventory (webapp-frontend/src) and browser behaviour
| Place | What | In plain browser |
|---|---|---|
| `main.tsx` | `init()` (try/catch already), `--tg-*`/`--tg-theme-*` overrides from `WebApp.themeParams`, `applyThemePref`, `data-vp-scheme` from `--tg-bg-color`, `themeChanged`/`theme_changed`, `AppRoot appearance` | init() throws are caught; themeParams absent -> light defaults only (no dark). Add `prefers-color-scheme` palette (CSS, gated by `html[data-vp-runtime="browser"]`) + matchMedia listener re-running `applySchemeAttribute`. |
| `index.html` | `telegram-web-app.js` (always loaded; in a browser creates `Telegram.WebApp` with `platform:"unknown"`, empty `initData`) | Add early inline runtime detector setting `data-vp-runtime` (no flash), title/meta/favicon. |
| `telegramBoot.ts` / `telegramPlatform.initTelegramPlatform` | ready/expand/disableVerticalSwipes/safe-area vars | skip entirely in browser (no-op) |
| `telegramChrome.ts` | setHeaderColor/BackgroundColor/BottomBarColor | no-op in browser (gated by bootTelegram skip + getWebApp absent) |
| `useBackButton.ts` + `backButtonStack.ts` | SDK BackButton via stack | browser adapter -> `platform/BackBridge.tsx` registry; shell renders in-page back; Escape triggers back for overlay entries (`hideNav=false`) |
| `useClosingConfirmation.ts` / `acquireClosingConfirmation` | WebApp.enableClosingConfirmation | `beforeunload` listener while owner count > 0 |
| `telegramPlatform.confirmAction` (9 call sites) | `showConfirm` else `window.confirm` | in-page confirm sheet (promise-based host mounted by AppShell) |
| `telegramLinks.openExternalLink` (payment, oferta, CSV) | SDK openLink -> WebApp.openLink -> `window.open(url,"_blank")` | `window.open(url,"_blank","noopener")` in browser |
| `telegram-safe-area.css` | `env()` + `--tg-safe-area-*` | vars absent -> 0, fine |
| `App.tsx` `getWebApp()?.close()` | session-expired close | coordinator's file; no-op in browser (note) |
| haptics | no `hapticFeedback` usage found | n/a |

### Design
- `platform/runtime.ts`: pure `detectBrowserRuntime(webApp, loc)` + module var `isBrowserRuntime()/setRuntimeMode()`. AppShell syncs it with `usePlatform().mode` (layout effect) so non-React code (confirm, links, back adapter, closing confirm) follows the real mode; initial value from heuristic.
- `platform/BackBridge.tsx`: store {visible, handler}; `useBackBridgeVisible()`; `<BackControl/>` rendered by AppShell (browser only).
- `platform/ConfirmHost.tsx`: pending-confirm store + sheet; `confirmAction` in browser mode resolves through it.
- `AppShell`: browser mode adds `.app-shell-web` class, topbar (back + mobile sign-out), ConfirmHost. `NavBar`: browser mode adds side-nav chrome (brand, sign-out footer); same buttons/aria-current. CSS (>=768px): fixed left nav 240px, centred column max 760px, nav stays on pushed screens; <768px unchanged bottom nav.
- Theme: dark palette + AA-safe hint/subtitle colours via CSS under `html[data-vp-runtime="browser"]` + `prefers-color-scheme`, explicit in-app override still wins (inline vars).
- Telegram mode: every new code path gated on runtime=browser; CSS gated by the attribute.

## Final (UTC 2026-10-18)
Active min total ~75 (cp1 12 + implementation 63), waiting ~12 (npm ci, builds, e2e runs), rework: 2 (BackBridge split into backStore.ts for node tests; runtime heuristic relaxed after an existing telegramPlatform unit test used a bare WebApp stub; tgui `--tg-theme-*` vars added after dark headings rendered black).

**Summary:** browser mode only (`data-vp-runtime="browser"`, set by index.html inline detector + main.tsx + AppShell from usePlatform().mode). >=768px: fixed left side nav 232px (same buttons/aria-current), centred column max 760px, nav kept on pushed screens; <768px unchanged bottom nav. In-page «Назад» (`BackBridge.tsx`/`backStore.ts`): useBackButton registers into the same stack via a browser adapter; Escape closes overlay entries (`hideNav=false`); no history pushes. Theme: AA-checked light/dark palettes by prefers-color-scheme (+ `--tg-theme-*` for tgui), in-app override still wins, no flash. Fallbacks: `confirmAction` -> in-page `ConfirmHost` sheet, `openExternalLink` -> `window.open(url,"_blank","noopener")`, closing confirmation -> `beforeunload`, bootTelegram/chrome skipped, new title/favicon. `<SignOutButton/>` rendered once in the shell top bar (mobile top-right; desktop fixed at the bottom of the side nav). Telegram mode: AppShell/NavBar/adapters render/behave as before (all new paths gated by runtime=browser).

**Files:** webapp-frontend/index.html, src/main.tsx, src/shell.css, src/telegramPlatform.ts, src/telegramLinks.ts, src/useBackButton.ts, src/platform/{AppShell,NavBar}.tsx, new src/platform/{runtime.ts,backStore.ts,BackBridge.tsx,confirmStore.ts,ConfirmHost.tsx}, tests/{platformRuntime,backBridge}.test.ts, e2e/scenarios/web/layout-{shell,flows}.spec.ts, scripts/e2e_seed_all.sh (ids 943001/2, 943010/11, 943020/21 via existing scenarios), shots in checkpoints/WEB-LAYOUT-shots/.

**Tests:** node --test all 385 pass; tsc + vite build clean; ruff clean; test_e2e_seed_integrity 3 pass; web layout specs: layout-shell 14/14 (desktop+mobile), layout-flows: home drill-down, subscription pay via window.open noopener (route-mocked, no payment), screenshots pass; Telegram-mode specs (not-onboarded, ready, telegram-back-home, session-back-button, home-discovery, plans-row-narrow, telegram-web-confirm, mobile-layout) pass (telegram-web-confirm needs reseed of 999621/999221 between runs). AUTH's `auth-login` test-login spec failed once in my stack (not mine; stack env had the test-login vars).

**Open / risks:**
1. SEAM (see WEB-LAYOUT-seam-request.md): App.tsx live-session branch (`v2Session`) and loading branch use a raw `<div className="app-shell">`, bypassing AppShell -> no in-page back / ConfirmHost there. Spec `layout-flows` «План -> предэкран -> Назад» FAILS until the coordinator applies it (2 lines). CSS column already applies to `.app-shell` in browser.
2. Some screens already have their own «← Назад» in the header (e.g. SubscriptionScreen); browser mode shows both (cosmetic duplicate).
3. WebKit not run. Live-workout width checked only through the 760px column rule, not by playing a session in the browser.

**Verify:** stack `WEB_AUTH_TEST_LOGIN=1 WEB_AUTH_COOKIE_SECURE=0 WEB_AUTH_IP_REQUEST_LIMIT=1000 WEB_AUTH_IP_POLL_LIMIT=100000 WEB_AUTH_IP_BAD_POLL_LIMIT=100000 bash /tmp/ux_stack.sh <wt> 8091 wl_8091`; then `cd webapp-frontend && node --test tests/*.test.ts && npx tsc -b && npx vite build`; `cd e2e && npx playwright test scenarios/web/layout-shell.spec.ts scenarios/web/layout-flows.spec.ts --retries=0` (reseed 943001/943002 journal_dedupe, 943020/21 session_recovery before reruns).
