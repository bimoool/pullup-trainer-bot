# Proposed sprints — for owner review (no implementation before review)

Each sprint delivers one complete user scenario, demonstrable on staging with screenshots and a journey E2E.
Estimates are active work for one worker in this repo; CI/staging time and owner decisions are extra.
**Reference gate:** sprints marked *ref-independent* fix behaviour the spec already defines (ACCEPTANCE
J-journeys, cross-cutting rules) and may start after this review. Sprints marked *ref-dependent* need the
blocked Crimpd observation (capture list in `SCENARIOS.md`) before their screen design is final.

## Sprint 1 — «План недели не обманывает» · ref-independent · 1–1.5 days
- **Scenario:** user with «Подтягивания» does a main session; the plan shows exactly when the next one is available, never offers a start that fails, future weeks start when allowed, A and Б are distinguishable.
- **Items:** UX-01, UX-02, UX-08, UX-09, (UX-20 disappears from the plan path).
- **Dependencies:** none (server rule exists); UX-08 wording uses the course's own A/Б names.
- **Acceptance:** J11 and J12 E2E green on a fresh user; screenshots of current week after a main session and weeks +1…+4; no plan row leads to a «нельзя» screen; revert-proof tests.

## Sprint 2 — «Одни и те же цифры везде» · ref-independent · 1–1.5 days
- **Scenario:** user finishes (or ends early) a workout and sees the same duration, sets and reps in Summary, Session detail, Journal card and Analytics.
- **Items:** UX-03, UX-04, UX-14, UX-17.
- **Dependencies:** owner picks the duration label (work time vs elapsed time) — one line decision.
- **Acceptance:** E2E: session with an AMRAP set and a pause → identical duration in 4 places, no «0:00» with logged sets; Journal totals = Analytics totals (or labelled split); timed exercise card shows time.

## Sprint 3 — «Первый запуск без тупиков» · partly ref-dependent · 1.5–2 days (+ owner decision)
- **Scenario:** fresh user: onboarding → course → plan → first live set without detours; the onboarding max is visible as their first result.
- **Items:** UX-06, UX-05, UX-23, UX-16; UX-07 only after the owner decides how bands are recorded.
- **Dependencies:** owner: (a) is the Замер a Tests result; (b) band-entry format (UX-07). Reference: first-run and template-add dialogs (wave-1 capture items 1–4).
- **Acceptance:** J1 E2E from S0 counts taps to first set and has no return to Home; Tests show the Замер; «Тренировку из моих» never shows a Save that cannot work.

## Sprint 4 — «Один понятный план» · ref-dependent · 2 days (+ owner decision)
- **Scenario:** user with a custom weekly plan (and optionally a course) sees one coherent plan: correct header, phase only for a course, per-week volume editing, past days marked, rest week named.
- **Items:** UX-10, UX-11, UX-12, UX-13.
- **Dependencies:** owner: presentation of the single-active-plan model; reference: Training Plans editor/week stepper observation (wave-1 items 12–13).
- **Acceptance:** J6 E2E (2,2,0,2) with steppers; screenshots light/dark/320; no «База» or «Курсов в плане нет» next to an active custom plan.

## Sprint 5 — «История последовательна» · NEEDS-OWNER first · 1 day after the decision
- **Scenario:** user browses old (pre-v2) and new course history: same card format, one deletion rule, confirmations that work inside Telegram.
- **Items:** UX-15 (+ remaining `window.confirm` in Journal), UX-19, UX-21.
- **Dependencies:** owner decision on deleting legacy course records (PROJECT_SPEC §3 safe-delete predicate).
- **Acceptance:** aged-profile journey (J2) shows legacy and v2 cards alike; delete follows the decided rule with an in-app sheet; a11y roles correct.

## Backlog outside sprints
UX-18 (verify on Telegram Web/Desktop first).

## Order and checkpoint
Recommended: S1 → S2 (independent, can run in parallel worktrees) → owner decisions + reference capture → S3 → S4 → S5.
Each sprint ends with a pushed checkpoint and staging screenshots; CI green is engineering evidence, not UX acceptance.
