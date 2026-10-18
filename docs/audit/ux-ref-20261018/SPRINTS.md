# Sprint plan v2 — for owner review (no implementation before review)

Replaces the cloud draft. Built from the full backlog (UX-01…UX-31) after the real-reference pass.
Gate: `docs/AGENT_EXECUTION_MODEL.md` § Reference audit to implementation gate (PR #340). **Nothing is
implemented.** Each sprint ends with a **working user scenario**, shown on staging with screenshots and a journey
E2E; CI green alone is not acceptance.

**Estimates** are active engineer-days for one worker in this repo, assuming: the existing v2 API/DB is reused;
the frontend patterns (`FormSheet`, `DayPicker`, plans screens) are reused; staging deploy/CI wait is **not**
counted; owner review of screenshots is not counted. «Plan-before-code» means the CLAUDE.md rule for schema/domain
changes: a written plan with numeric examples, agreed, then code, tests on every plan example, revert-proof test.

## Dependency graph

```
S1 ─┐                      ┌─ S5 (needs S4)
S2 ─┼─► S3 ─► S4 ─────────┤
    │                      └─ S6 (needs S4)
S7 independent (card-format part waits for the Wave-4 freeze)
```
S1 and S2 are independent and may run in parallel worktrees; S5/S6 may run in parallel after S4.

## S1 — «План недели не обманывает» · ref-independent · 1.5–2 d
- **Scenario:** user with «Подтягивания» does a main session; the plan shows the next valid date, never offers a start that fails; future weeks start when allowed; A/Б distinguishable; custom-plan rows have the same actions in every editable week and cannot be moved into a past day silently.
- **Items:** UX-01, UX-02, UX-08, UX-09, UX-31 (UX-20 disappears).
- **Dependencies:** none (server rule exists).
- **Acceptance:** J11 + J12 E2E on a fresh user; screenshots of the current week after a main session and weeks +1…+4; no plan row leads to a «нельзя» screen; current-week rows expose «⋯»; a past day is disabled/labelled «пропущено», with a test; Move sheet has «Отмена».
- **Assumption:** UX-31 «real client» Back behaviour is verified on staging in Telegram Web.

## S2 — «Одни и те же цифры везде» · ref-independent · 1.5 d
- **Scenario:** a workout is finished (or ended early); Summary, Session detail, Journal card and Analytics show the same duration, sets and reps.
- **Items:** UX-03, UX-04, UX-14, UX-17.
- **Dependencies:** none; the label question is **closed** (`DECISIONS.md`: active time, 0 = «без длительности»).
- **Acceptance:** E2E: session with an AMRAP set and a pause → identical duration in 4 places; no «0:00» with logged sets («без длительности» only for 0 s); Journal totals = Analytics totals or the split is labelled; a timed-exercise card shows time.

## S3 — «Первый запуск без тупиков» · 2 d
- **Scenario:** fresh user: onboarding → course → plan → first live set without detours; the onboarding max is visible as «Стартовый замер»; «Записать» offers catalogue workouts.
- **Items:** UX-06, UX-05 (Q1 default), UX-23, UX-16, UX-07 (structured band picker, prefill from «Мои резины»/previous block, same completeness rule), UX-10 header part.
- **Dependencies:** none technical; Q1 default stands unless vetoed.
- **Acceptance:** J1 E2E from S0 counts taps to the first set and has no return to Home; Tests card shows «Стартовый замер»; a band setup cannot be saved incomplete (V5.6 §8) and offers choices, not free text; «Тренировку из моих» never shows a Save that cannot work.

## S4 — «Недельный редактор плана» · plan-before-code · 4–5 d
- **Scenario:** user builds a 4-week plan: sets per-workout weekly quantity, sees weekly totals and phases, inserts and deletes a week with confirmation, reloads and finds it identical.
- **Items:** UX-24, UX-12, UX-13, UX-10, UX-11 (duplicate inside the week view), UX-28 (confirmations for week/workout deletes).
- **Dependencies:** S1 (row actions); **plan-before-code first** (0.5 d): per-workout weekly quantity data model, interaction with the existing `custom-plans` rotation model, archive-table check (CLAUDE.md schema rule), Q2 default = integers.
- **Acceptance:** E2E: 2/2/0/1 for A and 1/1/1/1 for B → totals row matches; insert/delete week with a confirmation naming what is lost; «Свободный пул» renamed; one entry point for «Добавить в план» and the weekly editor; screenshots light/dark/320.
- **Risk:** largest sprint; if the data model needs a migration, run it locally against non-empty tables before staging (CLAUDE.md deploy rule).

## S5 — «Расписание недели и повтор в день» · 2–3 d
- **Scenario:** user opens a week, sees how many sessions of each workout still have to be placed and the load per day, places one workout twice on Tuesday, moves one to Thursday.
- **Items:** UX-25, UX-26.
- **Dependencies:** S4.
- **Acceptance:** E2E: quantity 2 placed twice on Tuesday → «×2», day total 2; move to Thursday updates both totals; quota spent → message «все занятия размещены» (no silent ignore); a done state ✓ on the card; category progress consistent after deleting a Journal entry.

## S6 — «Жизненный цикл плана» · 2–3 d
- **Scenario:** user creates a plan that starts next week, sees it under «Предстоящие», changes its start date, clones it, deletes it with a confirmation.
- **Items:** UX-27, UX-29 (week notes, optional), remaining UX-28.
- **Dependencies:** S4.
- **Acceptance:** E2E: create → appears in «Предстоящие»; the picker blocks days of the active plan with a visible reason; clone identical; delete confirmation; empty-state texts.

## S7 — «История последовательна» · 1 d (+ Wave-4 gate for the card-format part)
- **Scenario:** user browses old (pre-v2) and new course history; deletion follows the decided rule with in-app confirmations that work inside Telegram.
- **Items:** UX-15 (presentation only), UX-19, UX-21, UX-30 (optional metric switch).
- **Dependencies:** none for the `window.confirm` replacement; a single card format waits for the Wave-4 freeze already planned in `MIGRATION_V2`.
- **Acceptance:** aged-profile journey (J2): delete shows an in-app sheet naming the consequence; a11y roles correct; no `window.confirm` in Journal.

## Totals and order

| | Sprints | Active days |
|---|---|---|
| Ref-independent (start after review) | S1, S2 | 3–3.5 |
| Needs the Q1 default only | S3 | 2 |
| Reference-model rework | S4, S5, S6 | 8–11 |
| Cleanup | S7 | 1 |
| **Total** | 7 sprints | **14–17.5 d** |

Recommended order: S1 ‖ S2 → S3 → S4 → S5 ‖ S6 → S7. Outside sprints: UX-18 (verify on a real Telegram client first).
Each sprint ends with a pushed checkpoint and staging screenshots.
