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
- [ ] Swiping down from the top of the app: does it close/minimize the Mini App unexpectedly mid-session? (record behaviour; not currently guarded — see notes)
- [ ] Edge-swipe back: leaves the app or goes back sensibly; nothing lost
- [ ] Status bar / safe area OK in both light and dark iOS appearance
- [ ] After backgrounding for ≥1 min and returning: no white/blank screen, data reloads
- [ ] Text is readable at your Dynamic Type size; nothing truncated ("По…", "Инт…")

## Known notes (from code inspection, need your eyes)

- The app does **not** call expand / closing-confirmation / disable-vertical-swipes / haptics. So an accidental swipe-down may minimize the app mid-session — record what actually happens (session should resume on reopen). This is a product decision if it's annoying; report as P2 unless data is lost (then P1).
- Summary screen has no Telegram Back button by design of the code (root/summary screens) — check it doesn't feel like a dead end.

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
