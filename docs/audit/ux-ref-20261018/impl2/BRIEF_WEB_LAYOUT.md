RUN MODE: LOCAL CODE
MODEL: STANDARD / SONNET
MODEL REASON: responsive layout and platform abstraction over existing shared screens; no new architecture
SESSION: NEW
TASK TYPE: IMPLEMENTATION
BASE SHA: the seam commit on `campaign/ux-ref-20261018` (given in your launch message); code base main e2ed40e
BRANCH / WORKTREE: `web/layout` / `/Users/kirillv./Documents/Claude Code/pullup-web-layout`
ACCESS: git, Docker, venv, npm, Playwright Chromium (+ WebKit if installed). Browser login is being built by WEB-AUTH in parallel; until its test-login helper reaches `campaign/ux-ref-20261018` (the coordinator will message you), develop against the Telegram-mode stack and unit/CSS-level checks; then rebase and add browser-mode E2E.
DELIVERABLE: pushed branch with the responsive shell, navigation, in-page «Назад», theme and platform fallbacks + `scenarios/web/layout-*.spec.ts`; checkpoint file `checkpoints/WEB-LAYOUT.md`
TIMEBOX: first checkpoint ≤ 15 min (inventory of Telegram-SDK coupling + design); then continue to the end
NEXT STATUS: first checkpoint pushed within 15 min
AUTHORIZED ACTIONS: edit owned files, run focused tests, commit, push own branch. No merge, no deploy.

# Task WEB-LAYOUT — one set of screens for the Mini App and for a mobile/desktop browser

Reuse the shared screens; **do not create a separate app**. Seams already exist: `platform/AppShell.tsx`, `platform/NavBar.tsx`, `usePlatform()` (`platform/mode.tsx`: `mode: "telegram" | "browser"`, `signOut`). `App.tsx` is the coordinator's.

## Inventory first (checkpoint 1)
List every use of the Telegram SDK / `window.Telegram.WebApp` in `webapp-frontend/src` (`telegramPlatform.ts`, `useBackButton.ts`, `useClosingConfirmation.ts`, `main.tsx`, theme/`--tg-*` variables, `confirmAction`, `openLink`, haptics, safe-area, `expand`, `ready`) and what each should do in a plain browser. Check that `main.tsx` does not throw in a browser (SDK `init()` etc.).

## Required behaviour in `mode === "browser"` (Mini App behaviour must stay byte-identical in `telegram` mode)
1. **Shell:** mobile browser (< 768 px) = current look with bottom nav; tablet/desktop (≥ 768 px) = a left side navigation (same tabs, same `aria-current` contract), centred content column with a sensible max width (live workout stays comfortably usable), no horizontal overflow at 320…1920 px.
2. **«Назад»:** in the Mini App the Telegram `BackButton` is driven by `useBackButton`. In the browser provide an in-page back control (top of the content column) wired to the **same handlers** (a registry in a new `platform/BackBridge.tsx`: `useBackButton` registers into it in browser mode, the shell renders the button when a handler is active), plus the browser's own back/forward must not break the app (no history pollution; Escape closes sheets).
3. **Theme without Telegram SDK:** derive light/dark from `prefers-color-scheme` (+ the existing in-app «Тёмная» override from display preferences); provide fallback values for the `--tg-*` CSS variables that Telegram normally injects; keep contrast ≥ AA in both themes; no flash of wrong theme.
4. **Platform fallbacks:** `confirmAction` → in-page confirm sheet (not `window.confirm`), `openLink` → `window.open(..., "noopener")`, `useClosingConfirmation` → `beforeunload` during a live workout, haptics/safe-area/header-color calls are no-ops; keyboard focus order and visible focus styles; sensible `<title>`, favicon, viewport meta.
5. **Sign-out control** in the shell when `usePlatform().signOut` is defined (profile area / side nav footer) — no logic, just the control.
6. **Subscription/payment in the browser:** screens must render and the pay button must open the payment link via `openLink` fallback **without performing any real payment in tests**; verify the paywall sheet works.

## Acceptance
- Unit tests for pure helpers; `tsc`, `vite build`, `node --test`.
- E2E `scenarios/web/layout-*.spec.ts` (projects `web-desktop` 1280×800 and `web-mobile` 390×844): navigation on both layouts, in-page «Назад» through a drill-down (Home → workout detail → back; plan → session pre-screen → back), theme light/dark by `colorScheme`, 320 px and 1920 px no overflow, confirm sheet, no console errors. Use the WEB-AUTH test-login after it lands.
- Existing Mini App specs for the screens you touched stay green (run: `not-onboarded`, `ready`, `telegram-back-home`, `session-back-button`, `home-discovery`, `mobile-layout`, `plans-row-narrow`, the parity `visual-*` and `a11y-review` specs).
- Screenshots (small PNGs) in `checkpoints/WEB-LAYOUT-shots/`: desktop 1280, tablet 820, mobile 390, light/dark.
