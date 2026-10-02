# iPhone QA checklist (staging)

**Target:** `https://staging.app.bimoool.com`, opened from the **staging test bot** in Telegram on a real iPhone.
**Build:** `develop/current` @ `4610cb6` (PR #226, draft). **Time:** ~15–25 min.
**Never** open production for this run. Staging has its own DB — anything you do here is disposable.

## Before you start

- Open the staging bot → the Mini App menu button. If the app asks for onboarding, complete it (staging DB is empty for your account).
- Create ONE disposable workout for the run: **Главная → Мои тренировки → Создать тренировку**, name it `QA-tmp`, add e.g. Подтягивания (reps, 3 sets). Use this workout for everything below. Only this session may be deleted in Journal.
- Do NOT delete anything else; do not touch protected STEP history.
- Mark each line **PASS / FAIL / BLOCKED / NOT TESTED** in the result table at the bottom (fill from your phone).

## 1. Launch

- [ ] App opens from the bot menu button; first screen renders (no white/blank screen, no spinner stuck >5 s)
- [ ] Top of the app is not hidden under the status bar / Telegram header; content is not cut at the notch
- [ ] Bottom nav (Главная · Планы · Журнал · Аналитика · Профиль) fully visible above the home indicator, not clipped
- [ ] Each of the 5 tabs opens and highlights correctly

## 2. Home

- [ ] «Программы» list visible; open a program → Telegram **Back button** (top-left) returns to Home
- [ ] «Мои тренировки» visible, `QA-tmp` listed
- [ ] «Создать» / «Создать тренировку» opens the editor; keyboard opens when typing a name and does **not** cover the field or the save button; closing keyboard restores layout
- [ ] Scroll the whole page smoothly; no rubber-band jump of the nav
- [ ] Navigate away and back: Home is in the same state, no reload flash

## 3. Plans

- [ ] From `QA-tmp` (or a program item) tap add-to-plan → pick a day → appears in **Планы**
- [ ] Open the plan week; item is on the day you picked
- [ ] Tap start → live session opens

## 4. Execution (use `QA-tmp`; repeat quickly for other types if you have them)

- [ ] **Reps:** log 3 sets with the numbers; the counter/targets are correct
- [ ] **Rapid double tap** on «Готово» / «Завершить»: only ONE set/finish is recorded
- [ ] **Time** block (if seeded): seconds count correctly, target shown
- [ ] **Max** block (if easy to add): attempts logged, no invented target
- [ ] **Interval** block (if easy to add): timer runs, auto-finishes to summary
- [ ] **Mixed** workout (reps → interval → max) if you built one: manual transitions work, no block jumps
- [ ] **Background**: press Home/swipe up mid-session, wait ~30 s, return → session still there, sets kept, timer still correct
- [ ] **Lock/unlock** phone mid-session (20 s) → back in app: no blank screen, session intact
- [ ] **Network off**: enable Airplane mode, log 2 sets → UI still accepts them (no error wall)
- [ ] **Network on**: disable Airplane mode → the sets sync (no duplicates, nothing lost)
- [ ] **Reconnect + Complete race**: Airplane on, log a set, Airplane off and immediately tap «Завершить» → session completes once, summary shows ALL sets
- [ ] **Reload/resume**: mid-session close the Mini App (swipe down), reopen from the bot → active session is restored with sets intact
- [ ] Telegram Back button during a live session asks/handles safely (does not silently drop the session)

## 5. Summary

- [ ] Summary shows the right totals for what you logged
- [ ] Leaving Summary (button or Back) lands on a sensible screen, not a blank/stale one

## 6. Journal

- [ ] The new result appears at the top of **Журнал**
- [ ] Open its detail: sets/values match; Telegram Back returns to the list
- [ ] Delete ONLY the `QA-tmp` session (disposable Builder session). It disappears; list stays consistent after reopening the tab
- [ ] (Do not attempt to delete any other entry)

## 7. Analytics

- [ ] **Аналитика** opens without an error
- [ ] Values look sensible for what you did (no NaN/∞/huge numbers)
- [ ] Switch Program ↔ Training: both render; no horizontal scroll

## 8. Profile

- [ ] **Профиль** opens; timezone/settings visible; sub-screens (FAQ etc.) open and Back works

## 9. iPhone-specific

- [ ] Keyboard never traps the UI (can always reach the field and scroll)
- [ ] Bottom nav is never hidden behind the keyboard-less home indicator or Telegram bar
- [ ] Swiping down from the top of the app mid-session must NOT collapse the Mini App (guarded by `disableVerticalSwipes`, Telegram ≥ 7.7 — see «Платформа Telegram»); closing via «Закрыть» asks for confirmation during a live session
- [ ] Edge-swipe back: leaves the app or goes back sensibly; nothing lost
- [ ] Status bar / safe area OK in both light and dark iOS appearance
- [ ] After backgrounding for ≥1 min and returning: no white/blank screen, data reloads
- [ ] Text is readable at your Dynamic Type size; nothing truncated ("По…", "Инт…")

## Known notes (from code inspection, need your eyes)

- Summary screen has no Telegram Back button by design of the code (root/summary screens) — check it doesn't feel like a dead end.
- Legacy screens (the old «Тренировка» tab: `WorkoutScreen`, `ElectiveScreen`, `FreeWorkoutScreen`, onboarding step «← Назад») still have only the on-screen «← Назад», no Telegram Back button. They are not on the 5-tab path; report only if you land on them.
- `window.confirm(...)` is used for delete / finish confirmations (works in Telegram, but iOS titles the dialog with the page host). Cosmetic; `Telegram.WebApp.showConfirm` would be the native replacement (not done — async refactor of 9 call sites, E2E relies on the dialog event).

## Платформа Telegram: проверено автоматически / требует устройства

Added by the platform audit (#224, branch `parallel/tg-platform-audit`). «Auto» = covered by `webapp-frontend/e2e/scenarios/parity/tg-platform.spec.ts` (Telegram mock with Bot API version / safe-area / call log) or unit tests in `webapp-frontend/tests/`. The mock proves **our code calls the right API at the right time**; only a real iPhone proves **Telegram/iOS honours it**. Everything in the right column needs your eyes.

| Area | Auto (mock / unit) | You check on the iPhone |
|---|---|---|
| **Expand + ready** (`initTelegramPlatform`, `src/telegramPlatform.ts`) | `ready()` and `expand()` are called at start on every version | Mini App opens at **full height** (not half-sheet); Telegram's own loading spinner disappears right after the first screen |
| **Disable vertical swipes** (Bot API 7.7+) | `disableVerticalSwipes()` called only when version ≥ 7.7 | Mid-session, drag down inside the app (Journal list, live screen): the Mini App must **not** collapse/minimise. Closing via the top-left «Закрыть»/chevron still works. On Telegram < 7.7 the old behaviour remains (record version: Settings → About) |
| **Closing confirmation** (Bot API 6.2+) | Enabled while a live session (reps/time/max or interval) is on screen, disabled on pre-screen/summary/tabs; version-gated | Start a live session → tap «Закрыть» / swipe the sheet down: Telegram asks «Закрыть приложение?» (no silent close). After «Завершить» → summary: closing is silent again |
| **BackButton** (`src/useBackButton.ts` + `backButtonStack.ts`) | Hidden on the 5 root tabs; shown on Workout Detail, Profile → Настройки/FAQ; one click = one step back (single subscription, top-of-stack handler — no double navigation); nested screens keep it visible when a child closes | Back chevron top-left: appears/disappears with screen depth, no flicker on transitions; Profile → Настройки/Ачивки/Резина/Замеры/FAQ/Подписка all go back one level; during a live session it asks to finish (confirm dialog), it does not drop the session |
| **Theme chrome** (`src/telegramChrome.ts`, `applyTelegramChrome()`) | Header / background / bottom-bar colours are derived from the shell tokens (`--vp-page-bg`, `--vp-card-bg`), light and dark; `setBottomBarColor` only ≥ 7.10, hex header only ≥ 6.9 (older: theme key) | No visible **colour seam** between Telegram's header and the app's top edge, nor under the bottom nav / home indicator, in iOS light **and** dark; also after Settings → Оформление → Светлая/Тёмная (the Telegram header must follow) |
| **Theme change while open** | `applyTelegramChrome()` is exported and re-run on theme-pref change; the `themeChanged` listener lives in `main.tsx` on branch `parallel/live-ux-fixes` | Switch iOS/Telegram theme while the app is open: app colours **and** Telegram header follow without reopening |
| **Safe areas** (`src/telegram-safe-area.css`: `--vp-safe-top/bottom` = max(env, tg safe) + tg content-safe) | With a mocked Bot API 8.0 inset: nav `padding-bottom`, content `padding-top/bottom`, sticky headers and the live transport shift by exactly the inset; `safeAreaChanged` updates them live; with no insets nothing changes | Bottom nav fully above the home indicator; top content not under the status bar/Telegram header (**also** when the bot opens the app fullscreen — Telegram ≥ 8.0 only); Live Session transport («Готов/Готово») above the home indicator and not covered by the nav |
| **Viewport height** | Audit only: `live.css` uses `100vh` then `100dvh` (correct for WKWebView); no `viewportHeight`/stable-height JS is needed | Live screen: transport sticks to the bottom with no jump when the keyboard opens/closes; no blank band at the bottom after rotating or after the sheet is expanded |
| **Decimal comma** (`src/decimalInput.ts`) | `inputmode="decimal"` text fields (live set value, Settings/Profile weight+height, body metrics, journal edit, onboarding weight, backdate/band weight) turn «78,5» into 78.5; letters/second separator dropped; saved value is 78.5 | Open Профиль → Настройки → Вес: the keypad shows a **comma** (RU keyboard), typing «78,5» shows 78.5 and saves; no field ever "forgets" what you typed. In a live session type a value → it logs. **Note:** the iOS decimal pad has no Return key — the keyboard closes when you tap «Готово» in the live logging panel (we blur the field) or tap outside |
| **iOS input zoom** | iOS-only CSS rule forces ≥ 16px inputs (`@supports (-webkit-touch-callout)`) — not testable in Chromium | Tap every kind of input (live value, note, Settings, search): the page must **not zoom in** and stay zoomed; check inputs did not get visibly bigger/clumsy |
| **autoFocus** | Audit: only the legacy `LiveWorkoutScreen` max-input uses `autoFocus` (not on the 5-tab path) | Nothing to do unless you reach the old «Тренировка» tab; there the keyboard may not open by itself on iOS — tap the field |
| **Haptics** (`src/vibration.ts`, gated ≥ 6.1) | Unit-tested gating + fallback to `navigator.vibrate` | Phase-end timer buzz on iPhone (Профиль → Настройки → «Вибрация в конце фазы»), and silent when switched off. Only phase-end uses haptics; there is no tap feedback elsewhere (by design) |
| **External links** (`src/telegramLinks.ts`) | Оферта / payment use `openLink` (SDK → `Telegram.WebApp.openLink` → `window.open`); CSV export uses `downloadFile` (8.0+) else `openLink` (was `window.open`, which iOS blocks after an `await`). No `t.me` links exist, so `openTelegramLink` is not needed | Settings → Данные → Экспорт CSV: Telegram asks to download (8.0+) or opens the link; Оферта opens in the in-app browser, Mini App stays alive |
| **Expired session (401)** | initData > 12 h (backend `auth.py`) → every API call now shows «Сессия Telegram устарела. Закрой приложение и открой его заново из бота.»; the boot screen also gets a «Закрыть» button | Not practical to force on a device (the 12 h limit is a constant, `INIT_DATA_MAX_AGE_SECONDS`). Only if you leave the Mini App open/backgrounded > 12 h and see it: the hint appears, «Закрыть» closes Telegram's sheet, reopening from the bot works |
| **MainButton / SettingsButton** | Audit: the app uses neither (own buttons everywhere), so there is no handler lifecycle to leak | Nothing |

Quick fail triage: a missing Back chevron → check Telegram version first (Bot API ≥ 6.1 needed); a colour seam → note light/dark and the Telegram version; swipe collapses the app → note the version (< 7.7 cannot be fixed).

## Result capture (copy into a Telegram note / reply)

Legend: PASS / FAIL / BLOCKED / NOT TESTED

| Section | Result | Notes |
|---|---|---|
| 1 Launch | | |
| 2 Home | | |
| 3 Plans | | |
| 4 Execution | | |
| 5 Summary | | |
| 6 Journal | | |
| 7 Analytics | | |
| 8 Profile | | |
| 9 iPhone-specific | | |

For every FAIL, one line each:

```
FAIL <section.item>
Screen:
Action:
Expected:
Actual:
Screenshot/video: yes/no
Severity: P0 (data loss / can't use) | P1 (core flow broken) | P2 (cosmetic/annoying)
```
