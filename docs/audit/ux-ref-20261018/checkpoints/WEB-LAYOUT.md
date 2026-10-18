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
