RUN MODE: LOCAL CODE
MODEL: STANDARD / SONNET
MODEL REASON: consistency fix across existing screens with a decided definition (active engine time); no new architecture
SESSION: NEW
TASK TYPE: IMPLEMENTATION
BASE SHA: e2ed40e5da46e8a2a743fd4a69f0f9e9b4d1d8e0 (main); campaign tip b769de6
BRANCH / WORKTREE: `ux/c-metrics` / `/Users/kirillv./Documents/Claude Code/pullup-ux-c`
ACCESS: git, Docker, shared venv, npm (network). Unverified: nothing external.
DELIVERABLE: pushed branch fixing UX-03/04/14/17 end to end + tests; checkpoint file `checkpoints/C.md`
TIMEBOX: first checkpoint ≤ 15 min; expected 2–3 days of active work, in pushed slices
NEXT STATUS: first checkpoint pushed within 15 min of start
AUTHORIZED ACTIONS: edit owned files, run focused tests, commit, push own branch. No merge, no deploy.

# Task C — one set of numbers everywhere (UX-03, 04, 14, 17)

Decided (`DECISIONS.md`, `PROJECT_SPEC` §Live): **duration = active engine time, pauses excluded; 0 s = «без длительности», never «0 мин»/«0:00» next to a session with logged sets.** Analytics minutes come from `duration_seconds`. Journal vs Analytics totals must agree or the difference must be labelled.
Read: backlog UX-03/04/14/17 (evidence files in `docs/audit/ux-ref-20261018/artifacts/`), `PROJECT_SPEC.md` (Live, Journal, Analytics sections), `TRAINING_SESSION_V2.md`.

## You own
Session summary / session detail / Journal v2 / Analytics code, both sides: frontend `SessionSummaryScreen*.tsx`, `SessionDetail*.tsx`, `JournalV2*.tsx`, Analytics screens, `webapp-frontend/src/apiV2.ts` (**only** session/journal/analytics types), backend session/journal/analytics endpoints and services (`app/web/routes_v2.py` **session/journal/analytics hunks only**, `app/web/schemas_v2.py` session/journal/analytics schemas only, `app/services/analytics*`, `app/domain/` duration/analytics helpers), tests for them, `e2e/scenarios/ux-c-*.spec.ts` (new).
**Do not edit** Home, Dashboard, `App.tsx`, routing, plan/inclusion code (A/B own them), `scripts/e2e_seed*`.

## Steps
1. **Checkpoint ≤ 15 min:** reproduce with failing tests: a session with ≥ 1 logged set and ~30 s of active work shows «0:00» in Session detail while Summary shows 0:30 (UX-03); early finish (~40 s) → detail «0:00», summary without duration; Journal card «Подходы 9 · Повторы 60» vs Analytics «53 · 8» for the same session (UX-04); timed-exercise card «—» (UX-14); session detail lacks band/assistance, Summary «Упражнений 2» counts blocks (UX-17).
2. **One source of duration:** a single helper producing `duration_seconds` (active time) used by Summary, Session detail, Journal card, Analytics minutes; define the display function once (frontend `formatDuration`: ≥ 60 s → «N мин», < 60 s and > 0 → «N с», 0/null → «без длительности»).
3. **Reps/sets totals (UX-04):** decide by the data: if «Всего повторений» excludes the AMRAP/max set, label the Analytics tiles precisely («в рабочих подходах») **and** show the split; otherwise include it. Journal and Analytics must agree for any session (test on the AMRAP example: 9 sets / 60 reps by hand).
4. **Timed exercises (UX-14):** the card shows total time and sets for timed exercises instead of dashes (seeded «Планка» example).
5. **Session detail (UX-17):** show band/assistance used per block; «Упражнений» counts exercises, not blocks.
6. E2E spec: finish a workout (and early finish) → identical duration in the 4 places; totals agree.

## Acceptance
Hand-computed expected values in tests (write the arithmetic in the test comment); revert-proof check done for UX-03 and UX-04; focused pytest + `tsc -b && vite build` + your specs green (ports 8041–8049); no «0:00»/«0 мин» for sessions with logged sets anywhere; only owned paths changed.
