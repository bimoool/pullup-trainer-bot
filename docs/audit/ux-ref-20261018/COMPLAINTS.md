# Original owner complaints — coverage check (2026-10-18, checkpoint 1)

The three complaints that the first two passes missed. Rule kept: the owner's account was **read only**
(SELECT in a `default_transaction_read_only=on` session over SSH with the deploy key; no write, no Mini App
session, no bot message). Production revision `bd80bc9` is an ancestor of the audited `main@e2ed40e`
(1 commit apart; `plan_occurrence.py`, `plan_convergence.py`, `WorkoutScreen.tsx`, `App.tsx`,
`CollectionsRow.tsx` identical) — so the code read here is what production runs.

| # | Complaint | Verified | Not verified | Backlog |
|---|---|---|---|---|
| 1 | telegram_id 65107390 sees 3 sessions instead of 2 | **Root cause found (OBSERVED in prod data + code)** | — | UX-32 |
| 2 | Where free electives are switched on and used | **Answered (OBSERVED in code + prod data)** | live tap-through on prod (would need a Mini App session as the owner) | UX-33 |
| 3 | Broken «Подборки» layout in real Telegram | **Not reproduced** in Chromium/WebKit with production-identical content | rendering inside a real Telegram client (Desktop/iOS/Android) — see below | UX-34 |

## 1. Three sessions instead of two — OBSERVED

Prod, user `telegram_id=65107390` (users.id 1), plan 13, week 1 = 12–18 Oct:

- `program_inclusions` #13: program 1 «Подтягивания», `status=active`, `completed_main_sessions=15`, last main session 17 Oct.
  **Snapshot is a legacy one**: strategy `step`, `schema_version 1`, **no frozen `slots`, no `schedule`**, `program_items` with `count_per_week = 3` (two rows).
- Catalogue `programs.frequency = {sessions_per_week: 3}`; slot `main`.
- `plan_items` of the week: ids 63, 64, 65 = `main` occurrences 1, 2, 3 (`source=program`), plus two frozen legacy aggregates (61, 62, `count_per_week 3`, `status=removed`). Occurrence 1 is linked to the completed session of 17 Oct.
- Code (`app/domain/plan_occurrence.py::derive_slots`): for a snapshot without frozen slots the count is taken from the catalogue (`frequency.sessions_per_week`), i.e. **3**; `plan_convergence._ensure_program_occurrences` materialises exactly that many.
- Requirement (`docs/domain/PULLUPS_V5_6.md` §schedule, owner decision, **version-scoped**): only a *new* inclusion of V5.6 is frozen with `sessions_per_week = 2`; inclusions of the older version — «и старые снимки без слотов» — keep their schedule, past sessions are not rebuilt.

**Conclusion.** The «3» is not a calculation bug: the owner's course connection predates V5.6, so it correctly keeps 3/week by the rule «old versions keep their schedule». The defect is the **product gap**: nothing on the card or the plan says *why* there are 3, and there is no way to move this connection to the 2-per-week schedule. One of the three is already done (17 Oct), so the owner sees «1 из 3» and two open rows — they expected «1 из 2». With the 3-day minimum spacing (OD-2) a third occurrence in a week is also the one that shows «Не успеть на этой неделе» (UX-01).
Proposal (needs a decision, `DECISIONS.md` Q3): explain the schedule version on the course card; offer an explicit, opt-in «перейти на 2 занятия в неделю» that changes only future weeks and never rewrites history.

## 2. Free electives — OBSERVED

- **Enabled where:** nowhere — there is no switch. They are always available; the only limits are `ELECTIVE_MAX_PER_WEEK = 2` (rolling 7 days) and type rotation (`available_elective_types`). Free by owner decision 2026-10-17 (`routes.py::get_elective_plan` docstring: «предусмотренные программой подтягиваний факультативы оставляем бесплатными»; no subscription check; arbitrary extra sessions stay paid).
- **Used where:** `ElectiveScreen` is mounted only from the **legacy `WorkoutScreen`** («🎯 Факультатив» in the mode row; and «Сделать факультатив» on the rest-day status, issue #94). Since issue #175 that screen **left the bottom navigation** (`App.tsx`: «"workout" … ушёл из NAV_TABS»). It is reached only through the button **«Перейти в обычную "Тренировку"»** on the blocked-start screens (`SessionPreScreen`, `DashboardV2Screen`) — the very dead end of UX-01/UX-20.
- Neither Home, Plans nor Journal mentions electives (Home screens in cloud pass 1 and the local WebKit probe).
- Prod data: owner has **0** `elective_workouts` and 0 elective sessions — consistent with «never found it».

**Conclusion.** The feature exists and is free, but is undiscoverable: it hangs behind a legacy screen entered from an error state. → UX-33.

## 3. «Подборки» layout in real Telegram — NOT reproduced

- Prod content = the content of a clean install: **1** published collection («Начни с подтягиваний», 20-char title, 99-char description, 1 program), 1 program in the catalogue.
- Local probe (`harness-local/l8-collections.mjs`, `l9-collection-detail.mjs`; isolated stand): Chromium **and WebKit 27 (iOS-like engine)**, widths 320 / 360 / 390, light + dark, Telegram-style `themeParams`. Home row and the collection screen: **no horizontal overflow, nothing clipped**. Observed cosmetic points only: the single card is ~2/3 of the width with an empty right gutter (258 px of 390) and 154 vs 174 px height at 320 (`artifacts-local/l8-*.png`); on the collection screen the label «ПОДБОРКА» sits on the edge of the cover gradient (`l9-detail-webkit-320-dark.png`).
- History: earlier staging audits found a ~250 px layout shift when the row loads late after «Назад» (A11 in `audit-staging-6475bc0` / `cb1593c`) and ellipsised protocol lines at 375 px; `7500c37` records the shift as fixed.
- **Unverified part (specific):** how the row renders inside a real Telegram client's WebView (safe-area insets, Telegram's own theme CSS variables on the owner's device, font metrics, `--tg-*` variables missing at first paint). Checking it needs either the owner's screenshot/screen recording of the broken screen or a driven Telegram session as the owner. I opened Telegram Desktop access and **stopped**: background control of that app is not possible, and taking over the screen of a personal messenger session was not proportionate for a read-only check. Not replaced by the seed profile or by the Chromium result.
- What would settle it: one screenshot from the owner's device of Home → «Подборки» (and which device/OS), or the console output of the Mini App on that device.
