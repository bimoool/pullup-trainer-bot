# Execution plan v4 — state after the first candidate, plus the parallel browser direction

> **State (2026-10-18, after candidate `0790221` on staging):** Block 1 (course → plan → А/Б → availability, electives) and Block 3's
> numbers part (UX-03/04/14/17) are implemented, gated and deployed to staging — **user acceptance is NOT finished** (see `ACCEPTANCE.md`;
> UX-34 still needs the owner's screenshot). Everything below that says «Block N» is the v3 plan; estimates in **engineer-days are
> effort units, not calendar time** (the first candidate: 3 parallel agents, 2 h 21 min wall clock, `checkpoints/COORDINATOR.md`).
> **New, owner-approved, runs in parallel with the UX tasks:** the **browser version** (Mini App + a self-standing browser app from the same
> screens). Three independent executors, separate branches/worktrees: **UX-EDITOR** (Block 2 below, checked against the observed Crimpd),
> **WEB-AUTH** (Telegram login from a plain browser + protected browser session), **WEB-LAYOUT** (responsive shell, navigation, «Назад», theme without
> the Telegram SDK). The coordinator owns `App.tsx` and integration; the seams (`src/platform/*`, Playwright projects `web-desktop`/`web-mobile`)
> are fixed before any parallel edit — see `impl2/OWNERSHIP.md`.

## v3 plan (kept for reference)

Replaces sprint plan v2. Built on the full backlog **UX-01…UX-34**, including the three original owner complaints
(`COMPLAINTS.md`). Gate: `docs/AGENT_EXECUTION_MODEL.md` § Reference audit to implementation gate (PR #340).

## How a block runs (the owner does not relay between sub-tasks)

- One worker owns a block from start to acceptance. Inside the block there are **short internal checkpoints** (CP): each is
  a commit + push to the block's branch, CI on that SHA, a staging deploy where the checkpoint changes UI, and a line in
  `docs/audit/ux-ref-20261018/CHECKPOINTS.md` (what changed, SHA, screenshots, what is next). The worker continues
  straight to the next CP.
- The worker stops and asks only for: (1) **block acceptance** by the owner on staging, (2) a **hard blocker** from the
  list under the block, (3) a failed gate that the worker cannot fix in its own scope. A CP is never a question.
- Plan-before-code (CLAUDE.md schema/domain rule) is a CP inside the block: written plan with numeric examples, then code;
  the plan is recorded in the repo, not sent to the owner for approval unless it contradicts a requirement.
- Every block ends with a working user scenario on staging, a journey E2E, screenshots (light / dark / 320), and the
  revert-proof check of the new tests (CLAUDE.md «доказать, что тест ловит баг»).

## Estimates: three separate numbers per block

- **Active work** — engineer-days of writing/reviewing/fixing, one worker; derived from the change set below.
- **CI/staging wait** — wall time the worker is not typing. Measured from the last runs of this repo: *Tests* ≈ 16 min,
  *E2E (Mini App)* ≈ 25 min (separate workflows, run in parallel), guarded staging deploy ≈ 5 min at most. A CP costs ≈ 30 min
  of wall clock but the worker starts the next CP meanwhile; only the final green run is on the critical path.
- **Owner acceptance** — the owner's time on staging at the end of the block.

Unknowns are listed per block with the way each is closed and the cost if it goes the bad way (the upper end of the range).

---

## Block 1 — «Курс → мой план → понятные А/Б → доступная тренировка и факультативы»

**Closes the path:** connected-course card → «Мой план» → rows named A / Б with honest states → the available workout
starts (or says exactly when it will) → free electives are found and used. Also answers complaints 1 and 2.

**Items:** UX-01, UX-02, UX-08, UX-09, UX-20 (vanishes), UX-06, **UX-32**, **UX-33**.
Not in this block: band entry UX-07 (first start only, Block 3).

### Change set (why the estimate is what it is)

| CP | Content | Touches | Active |
|---|---|---|---|
| 1.0 | **Plan-before-code**: occurrence state model (startable / «доступно с <дата>» / «не уместится на этой неделе») for current and future weeks; legacy-snapshot fixture modelled on the owner's real shape (inclusion with no frozen slots, `count_per_week 3`, one done occurrence); opt-in migration rules with numeric examples. No schema change (snapshot is JSONB) → the five `*_archive_admin_reset` tables are not affected | docs + examples | 0.5 d |
| 1.1 | Backend: per-occurrence state and label (A/Б from the progression sequence), schedule-version fact (`sessions_per_week`, legacy flag) in the plan/course responses; unit + integration tests incl. the legacy fixture | `app/domain/plan_occurrence.py` (450 lines), `app/services/plan_view.py` (273), `plan_convergence.py` (557), `app/web/routes_v2.py` (1853, plan/course endpoints only), `tests/test_services`, `tests/test_web` | 1–2 d |
| 1.2 | Plans screen: row states, no «Начать» that cannot succeed, future weeks startable, A/Б names, wording A/Б unified; J11/J12 E2E | `DashboardScreen.tsx` (1440), `SessionPreScreen.tsx` (708, dead-end copy), copy files, `e2e/scenarios` | 1.5–2 d |
| 1.3 | Course card and Program detail: «Добавить в план» → «Открыть план / Начать»; schedule line («Расписание вашей версии: 3 занятия в неделю»); weekly elective counter | `HomeScreen.tsx` (647), program detail screen, small API additions | 0.5–1 d |
| 1.4 | Electives reachable: entry on the course card, on the rest-day plan state, in Home «+»; explanatory line (free, up to 2 per week, no effect on progression); reuse `ElectiveScreen` (290) and `/api/elective/*` | `HomeScreen.tsx`, `DashboardScreen.tsx`, `App.tsx` (588, routing out of the legacy screen), E2E | 1–1.5 d |
| 1.5 | **Opt-in «перейти на 2 занятия в неделю»** (Q3 default): re-freeze main slot for future weeks, drop surplus *open* future occurrences, keep done ones, history/progression/counters untouched, repeat convergence = 0 changes | `plan_convergence.py`, new service method + endpoint, tests on the legacy fixture incl. a started-but-unfinished future occurrence | 2–2.5 d |
| 1.6 | Integration: full journey on a fresh profile **and** on the legacy fixture; staging screenshots; owner-ready notes | e2e, `CHECKPOINTS.md` | 0.5–1 d |
| | **Block 1 active total** | | **7–10.5 d** (≈ 5–8 d if Q3 = «explanation only», CP 1.5 dropped) |

### Unknowns and how they are closed
- **Future-week availability needs a projection** of when earlier planned sessions would happen (spacing is computed from the last *actual* main session). Closed in CP 1.0; bad case +0.5 d (already in the 1–2 d of CP 1.1).
- **How many other prod users carry a legacy snapshot** — one read-only `SELECT count(*)` before CP 1.5; if many, the opt-in needs a bulk safety review (+1 d) but still no automatic migration.
- **Started-but-unfinished future occurrences** when switching 3 → 2: rule decided in CP 1.0, covered by a test.
- **Hard blockers (stop and ask):** the opt-in rule contradicts an existing requirement discovered while modelling; production data shows a snapshot shape not covered by the fixtures.

**CI/staging wait:** 4–5 pushed CPs ≈ 2–2.5 h of wall clock in total, not additive to active work; critical path = the last green Tests + E2E (≈ 30 min) + staging deploy (≈ 5 min).
**Owner acceptance:** ≈ 40 min on staging: (a) owner-shaped legacy account walk-through («1 из 3» explained, opt-in, 2 rows), (b) fresh profile walk-through, (c) electives from the card.

---

## Block 2 — «Недельный редактор плана и расписание недели» (next whole block, after Block 1)

**Closes the path:** build a 4-week plan with per-workout weekly quantities and phases → place sessions on days (including the
same workout twice in one day) → move, remove, see progress → reload and find everything identical.

**Items:** UX-24, UX-12, UX-13, UX-10, UX-11, UX-25, UX-26, UX-28, UX-31.
**Depends on:** Block 1 (row states and row actions).

| CP | Content | Touches | Active |
|---|---|---|---|
| 2.0 | **Plan-before-code**: per-workout weekly quantity model against the existing `custom_plans` (`workouts`, `weeks`, `repeat`, rotation «по очереди») and the occurrence materialisation; how existing custom plans migrate; whole-number quantities (Q2 default); archive-table check | docs, examples, possibly one migration | 1 d |
| 2.1 | Backend: quantities per workout per week, totals, insert/delete week, convergence of custom occurrences; migration of existing plans (run **locally against non-empty tables first**, CLAUDE.md deploy rule) | `plan_convergence.py::_ensure_custom_occurrences`, `app/db/models*`, repositories, routes, tests | 2.5–3 d |
| 2.2 | Editor UI replacing the «2 2 0 2» form: steppers, totals, phases, insert/delete week with confirmation (UX-28), one entry point from «Добавить в план» | `CustomPlanScreen.tsx` (135 → rewrite), `AddToPlanScreen.tsx` (173), new screens | 2–2.5 d |
| 2.3 | Week schedule: «осталось разместить N», per-day totals, same workout twice on a day shows «×2», quota-spent message, move between days | new screen + `DayPicker` reuse, `MovePlanItemScreen.tsx` (102) | 1.5–2 d |
| 2.4 | Row actions on every editable row, past days disabled or «пропущено», visible Cancel, «Свободный пул» renamed, header de-duplication (UX-10/11/13/31) | `DashboardScreen.tsx` | 1–1.5 d |
| 2.5 | Progress presentation: done ✓ on card, per-category counters, consistent after deleting a Journal entry (UX-26) | `DashboardScreen.tsx`, `plan_view.py` | 0.5–1 d |
| 2.6 | Integration E2E (create → schedule → move → remove → reload), screenshots light/dark/320 | e2e | 0.5–1 d |
| | **Block 2 active total** | | **9–12 d** |

**Unknowns:** (1) whether quantities fit the existing JSON columns or need new columns (decided in CP 2.0; the migration branch is the upper end of CP 2.1); (2) rotation semantics of old plans after conversion (test on aged profiles); (3) Q2 = «0.5 needed» would add one reference observation and a numeric type (+1–1.5 d).
**Hard blockers:** a migration that cannot be made lossless for existing custom plans.
**CI/staging wait:** 6 CPs ≈ 3 h wall clock in total; migration CP adds the local run against a non-empty database and one guarded staging deploy.
**Owner acceptance:** ≈ 45 min: build the 4-week plan from scratch, repeat in a day, move, delete, reload.

---

## Block 3 — «Одни и те же цифры и чистый первый запуск»

**Closes the path:** finish a workout → identical duration/sets/reps everywhere; fresh user → course → first live set without a
return to Home, with a structured band setup.
**Items:** UX-03, UX-04, UX-14, UX-17, UX-05 (Q1 default), UX-23, UX-16, UX-07, UX-34 (collections hardening), UX-19.
**Depends on:** none technical; can run in parallel with Block 1 in its own worktree (different files: Journal/Analytics/Home).

| CP | Content | Active |
|---|---|---|
| 3.1 | One duration source (active engine time; 0 s → «без длительности»), Summary / Session detail / Journal / Analytics; totals labelled; timed-exercise card | 1.5–2 d |
| 3.2 | «Стартовый замер» line on Tests, ГТО hint text, «Записать» lists catalogue workouts, neutral search heading | 1–1.5 d |
| 3.3 | Band setup pickers with prefill and the V5.6 completeness check | 1.5–2 d |
| 3.4 | Collections hardening (full-width single card, reserved height, `min-width:0`) — **final fix after the owner's screenshot** | 0.5–1 d |
| | **Block 3 active total** | **4.5–6.5 d** |

**Unknowns:** the cause of the real-Telegram collections defect (needs the owner's screenshot — the only owner input in the plan);
analytics tile semantics after CP 3.1.
**CI/staging wait:** 3–4 CPs ≈ 2 h wall clock. **Owner acceptance:** ≈ 30 min incl. the screenshot of Home on the real device.

---

## Block 4 — «Жизненный цикл плана и история»

**Closes the path:** create a plan that starts next week → see it under «Предстоящие» → change its start, clone, delete with a
confirmation → browse old and new history with in-app confirmations.
**Items:** UX-27, UX-29, UX-30, UX-15 (presentation), UX-21, remaining UX-28.
**Depends on:** Block 2 (editor); UX-15/21 part has no dependency.

| CP | Content | Active |
|---|---|---|
| 4.1 | Upcoming / In progress / Completed, start-week picker blocking overlapping days **with a reason**, change start, clone | 2.5–3 d |
| 4.2 | Delete plan/week confirmations, empty-state texts, week notes (optional) | 1–1.5 d |
| 4.3 | Journal: in-app sheet instead of `window.confirm`, consequence text; card-format unification waits for the Wave-4 freeze | 0.5–1 d |
| 4.4 | Analytics metric switch (optional) | 0.5–1 d |
| | **Block 4 active total** | **4.5–6.5 d** |

**Unknowns:** Wave-4 freeze date (card format); whether analytics metric switch is wanted before the duration semantics settle.
**CI/staging wait:** 3 CPs ≈ 1.5–2 h wall clock. **Owner acceptance:** ≈ 30 min.

---

## Totals and order

| | Active work | CI/staging wait on the critical path | Owner acceptance |
|---|---|---|---|
| Block 1 | 7–10.5 d | ≈ 40 min | ≈ 40 min |
| Block 2 | 9–12 d | ≈ 1 h (incl. migration deploy) | ≈ 45 min |
| Block 3 | 4.5–6.5 d | ≈ 40 min | ≈ 30 min + 1 screenshot |
| Block 4 | 4.5–6.5 d | ≈ 40 min | ≈ 30 min |
| **Total** | **25–35.5 d** | ≈ 3 h | ≈ 2.5 h |

Why it is larger than plan v2 (14–17.5 d), by source: the three owner complaints add UX-32/33/34 ≈ +5–7.5 d (opt-in migration 2–2.5, schedule
explanation and row states ≈ 1.5–2, elective entries 1–1.5, collections 0.5–1); the rest (≈ +5–10 d) is what v2 left out: a plan-before-code CP in
Blocks 1 and 2, an integration CP with screenshots per block, the lossless migration of existing custom plans, and the editor estimated by its
change set (its data-model unknown is the upper end), not by a flat guess.
If Q3 = «explanation only» the total falls by 2–2.5 d; if Q2 = «0.5 needed» it grows by 1–1.5 d.

**Order:** Block 1 ‖ Block 3 (separate worktrees) → Block 2 → Block 4. Outside the blocks: UX-18 (verify on a real Telegram client first).
The owner's calendar view: three acceptances in sequence, one screenshot, and vetoes of Q1–Q3 only if they disagree with the defaults.
