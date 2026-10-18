RUN MODE: LOCAL CODE
MODEL: STANDARD / SONNET
MODEL REASON: data-model design on an existing plan model plus UI work against an observed reference; no cross-system architecture
SESSION: NEW
TASK TYPE: IMPLEMENTATION (phase 1: DESIGN CONTRACT ONLY — stop after the contract checkpoint)
BASE SHA: the seam commit on `campaign/ux-ref-20261018` (coordinator records it in `checkpoints/COORDINATOR.md` and in your launch message); code base main e2ed40e
BRANCH / WORKTREE: `ux/editor` / `/Users/kirillv./Documents/Claude Code/pullup-ux-editor`
ACCESS: git, Docker, venv, npm. Reference evidence is in the repo (`docs/audit/ux-ref-20261018/REFERENCE.md`, `reference/screens/`, `COMPARISON.md`, backlog UX-24/12/13/25/26/28/31). The real Crimpd emulator is **not** available to you.
DELIVERABLE: phase 1 — `docs/audit/ux-ref-20261018/checkpoints/UX-EDITOR-contract.md` pushed; phase 2 (after the coordinator's «continue») — the implemented editor and schedule with tests
TIMEBOX: phase 1 ≤ 30 min of active work; phase 2 as long as it takes, in pushed slices
NEXT STATUS: contract pushed, then stop and report
AUTHORIZED ACTIONS: edit owned files, run focused tests, commit, push own branch. No merge, no deploy.

# Task UX-EDITOR — weekly plan editor and week schedule (backlog UX-24, 12, 13, 10, 11, 25, 26, 28, 31)

Goal (from the audit, verified on the real Crimpd — `REFERENCE.md` R-1…R-4): a plan has weeks; each workout in the plan has a **quantity per week**
(integers in this campaign — proposal Q2), each week has a phase label, totals per week are visible; **days are assigned afterwards per week** in a
schedule view that shows «осталось разместить N» per workout and a total per day; the same workout can be placed twice in one day; sessions can be moved
(including across weeks — ours is richer than the reference) and removed **with a confirmation** (documented difference: reference deletes silently); rows in
every editable week expose the same actions; past days are disabled or labelled «пропущено»; «Свободный пул» is renamed (the reference says «THIS WEEK»).

## Phase 1 — contract first (stop afterwards)
Write `checkpoints/UX-EDITOR-contract.md` containing:
1. What exists today (read `app/services/plan_convergence.py::_ensure_custom_occurrences`, `custom_plans` model (`workouts`, `weeks`, `repeat`, `preferred_weekdays`), `routes_v2.py` custom-plans and plan-items endpoints, `CustomPlanScreen.tsx`, `AddToPlanScreen.tsx`, `MovePlanItemScreen.tsx`, `DashboardScreen.tsx`).
2. The data model for **quantity per workout per week**: where it is stored (prefer the existing JSON columns / plan_items rows with **no migration**; if you believe a migration is unavoidable, prove it with numbers and mark it a contract request), how existing plans (rotation «по очереди» with `weeks=[2,2,0,2]`) convert **without changing what the user sees**, and how history stays untouched.
3. API changes (additive) with request/response examples.
4. **Numeric examples, hand-computed**, at least: (a) 4-week plan, workout A 2/2/0/1 and workout B 1/1/1/1 → per-week totals 3/3/1/2; (b) an existing custom plan `weeks=[2,2,0,2]` with 2 workouts rotating → the equivalent per-workout quantities and the occurrences materialised for the current week (today = the date in your checkpoint); (c) insert a week after week 2 → renumbering and what happens to already-done sessions; (d) delete a week with 1 done + 1 open session → rule; (e) one workout quantity 2 on one day → two occurrences, day total 2, «осталось 0».
5. Acceptance tests you will write (names + the exact expected values) and the UI states (empty week, week with rest phase, quota exhausted message «все занятия размещены»).
6. Risks and the checkpoint split for phase 2.
Push. Report to the coordinator. **Do not start phase 2 before the «continue» message.**

## Phase 2 (after «continue») — see the plan you wrote; additional rules
- Preserve existing plans and history; run a conversion check on aged seeds (`scripts/e2e_seed.py` aged profiles) — before/after identical visible plan.
- Do not touch `App.tsx`; navigation remains inside `DashboardScreen`.
- Confirmations are in-app sheets (not `window.confirm`).
- E2E: `scenarios/ux-editor-*.spec.ts` for: create 4-week plan → totals; repeat in one day «×2»; move across weeks; remove with confirm; reload identical; the aged-plan conversion.
- Revert-proof check for the key tests; hand-computed expected values in comments.
