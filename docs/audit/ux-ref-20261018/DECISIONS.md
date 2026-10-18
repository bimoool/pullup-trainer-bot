# Cloud-audit questions checked against existing requirements

Rule: nothing already recorded is re-asked. Sources: `docs/PROJECT_SPEC.md`, `docs/domain/PULLUPS_V5_6.md`,
`docs/domain/ACCEPTANCE_JOURNEYS_V2.md`, `docs/domain/MIGRATION_V2.md`, `CLAUDE.md`.

## Answered by requirements (no owner action)

| Question (cloud audit) | Answer in the requirements | What follows |
|---|---|---|
| **Deleting history** (UX-15) | `PROJECT_SPEC` «Безопасное удаление Builder-сессии»: hard delete only when the backend **proves** it safe (finished, not program-backed, user-owned snapshot, not a STEP role); everything unproven → 409 with a visible reason (`delete_reason`). v2 course sessions are not deletable. Legacy (`legacy_backfill`) cards keep «Удалить» via `/api/history` because legacy writers are **not frozen until Wave 4** (`PROJECT_SPEC` §single history, `MIGRATION_V2` §4/§6). | Policy is decided. UX-15 reduces to presentation: replace `window.confirm` (blocked in Telegram Web, `docs/incidents.md`) by an in-app sheet that names the consequence; one card format after the Wave 4 freeze. The reference deletes any log and un-credits the plan at once — we differ because deletion would rewrite progression (documented reason). |
| **Duration** (UX-03) | `PROJECT_SPEC` §Live: «Длительность — активное время движка (паузы исключены); 0 секунд — «без длительности», а не «0 мин»»; Analytics minutes from `duration_seconds`; «не выдумываем длительность». | Label decision is closed: active engine time. «0:00» next to a session with logged sets is a **defect**. The reference's estimated durations are not copied. |
| **Band / assistance recording** (UX-07) | `PULLUPS_V5_6` §8: a setup is ready only when complete — model/name, colour, attachment, foot/knee position; no kilograms for bands; order from the personal list. | The completeness rule is decided. The input control (free text vs pickers, reuse from «Мои резины»/previous block) is a design choice with a recommended default (pickers + prefill), not an owner question. |
| **Starting measurement** (UX-05) | `PROJECT_SPEC` §tests: test results are out of progression and do **not** change the onboarding baseline; the Tests card says so. Baseline feeds the level (`PULLUPS_V5_6` §entry inputs). | Semantics decided: baseline ≠ test result. Only the presentation is open → Q1 with a default. |
| Min rest, future weeks | J11/J12 in `ACCEPTANCE_JOURNEYS_V2`, OD-2 resolved = 3 | Defects UX-01/02, nothing to decide. |
| Direct start credits the plan? | J7 + spec: it does not for a course occurrence | Reference credits by date; we keep ours. |
| Replace our plan UX by the reference model? | Owner mandate 2026-10-02 (`crimpd-reference`): Crimpd 8.5.x is the functional reference, differences need a documented domain/platform reason | Default = replicate the weekly-quantity + per-week schedule model (UX-24/25/27); intentional differences are listed in `REFERENCE.md` §Not to copy. |

## Genuinely open — one list

| # | Question | Default used in the sprint plan | If you disagree |
|---|---|---|---|
| **Q1** | Where does the onboarding «Замер» show in Profile → Tests? | A labelled read-only line «Стартовый замер: 6 (из анкеты)» on the Tests card; it is **not** a test result and never enters the test history (keeps the spec rule). | Say «as first test result» — then the spec line about the baseline must be amended and `BodyMetric`/test storage touched (+0.5 d). |
| **Q2** | Weekly quantity per workout: whole sessions only, or also 0.5 (the reference steps by 0.5)? | Whole sessions only. The meaning of 0.5 (every other week? half session?) was **not observable** — the stepper accepted it, the week credit semantics are UNKNOWN. | Say «0.5 needed» — then one more reference observation (credit of a 0.5 slot) and a numeric column instead of integer (migration + archive-table check). |

Not asked (design defaults, veto allowed): past days in a current week are disabled or labelled «пропущено» (reference behaviour UNKNOWN); overlapping plan start dates are disabled with a visible reason; confirmations on every destructive plan edit.
