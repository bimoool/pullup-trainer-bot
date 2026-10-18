# Reference vs ours — the plan journeys

Reference column = real Crimpd 8.5.3 (`REFERENCE.md`). Ours = our product on `main@e2ed40e`:
cloud pass 1/2 (`artifacts/`, `PASS2.md`) **plus** the local pass of this session on an isolated stand
(`artifacts-local/`, scripts `harness-local/l*.mjs`: container built from `Dockerfile.web`, throw-away Postgres,
port 8012; no shared data, production and main untouched).

Evidence tags: **O** observed · **I** inferred · **U** unknown. «ours-L» = observed in the local pass.

| Journey | Reference (O) | Ours | Gap → backlog |
|---|---|---|---|
| **Create a plan** | «+» → one form: name, duration (wheel), start week (calendar, overlapping days disabled), optional goal; saves into an editor; weeks auto-phased Base/Build/Rest | Plans tab: «Свой план по неделям» form (ours-L `l5-01-form.png`): Название (default «Свой план»), workouts as checkboxes «по очереди» (rotation), free-text «Тренировок по неделям 2 2 0 2» + «Повторять по кругу», day buttons Пн..Вс labelled «подсказка, не обязательно»; no duration/start week/goal; phase label «База» only | no duration/start/goal, rotation instead of per-workout quantities, free text instead of steppers → **UX-12, UX-24, UX-27** |
| **Add workouts** | «Add Workouts» sheet (search, Category/Equipment/My Workouts filters, expand row, toggle +/−); added at 0/week; also «Add to Plan» → New / Existing plan | Workout detail «Добавить в план»: choose **one day** or «Свободный пул» → «Добавить» adds ONE item to the **current week only** (ours-L `l2`, `l3`); weekly builder is a separate entry; no multi-select picker in the plan | two disjoint paths, no quantity model → **UX-24**, UX-06 |
| **Repeat in the same day** | Week Schedule: each tap on a day adds one session (cycle 0→N→0), per-day totals row; one workout can sit twice in a day | Works but only by running «Добавить в план → Пн» again: two identical rows «L Тяга 0/1» under ПОНЕДЕЛЬНИК, no «×2» or per-day total (ours-L `l3`) | capability exists, not discoverable, no totals → **UX-25** |
| **Distribute across weeks** | per-workout `−/+` (0.5 step) per week; totals + hours per week; phase per week; insert/delete week; week notes | text field with space-separated numbers for the whole plan; same day pattern for every week; add/delete week not possible; phase fixed | **UX-12, UX-24, UX-29** |
| **Move** | re-pick the day inside the week (no cross-week move) | richer: row «⋯» → «Перенести»: pick any week + day or «Свободный пул» (ours-L `l6`). But: current-week rows have **no «⋯»** (only «Начать», ours-L `l4`/`l5`); move into a **past day** accepted silently (ours-L `l7`: four sessions on Mon 12 Oct while today is 18 Oct); move screen has no in-page Back (Escape does nothing; Telegram BackButton not rendered in harness) | **UX-31** |
| **Delete** | un-pick day / «Remove From Plan» / «Delete Week» — **no confirmation**; «Delete Training Plan» — confirm sheet | «Убрать из плана» — inline confirm «Убрать «L Тяга» из плана? [Убрать][Отмена]» (ours-L `l6`); «Остановить план» for a custom plan | our safer pattern is correct → keep, document as intended difference **UX-28** |
| **Execute** | Start Workout from detail (not occurrence-bound); player; **nothing saved until Log form Save**; killed process → no resume, no partial log | plan row «Начать» runs the occurrence; summary, evaluation, «Сохранить»; reload resumes the same set and timer (pass 2 O) | ours stricter and better; durations → **UX-03** |
| **History** | flat day list, card = Intensity / Completion / TUT / **Est.** Duration / Workload; delete log = action sheet, plan reverts instantly; future dates accepted (mis-filed) | Journal cards: sets, reps, effort; v2 course cards cannot be deleted, legacy cards can with `window.confirm` | **UX-03, 04, 14, 15, 17** |
| **Plan progress** | per-category rings (done/planned), per-card badge 0/1 → green ✓, derived by date+workout from logs | per-week counter «0 из N», per-row «0/1»; direct start does not credit (J7 by spec) | rings/✓ missing → **UX-26** (credit rule stays: spec J7) |
| **Plan lifecycle** | In Progress / Upcoming / Completed tabs, one active plan, clone, change start date, delete (confirm), empty states | «Сейчас / Завершённые», «Остановить план» only; course and custom plan mixed (UX-10) | **UX-10, UX-27** |
| **Analytics** | metric dropdown (Workouts Logged / Duration / TUT / Estimated Workload), 1 Mo. / 3 Mo. / Custom | tiles + per-category split (O cloud); no metric switch (I) | **UX-30**, UX-04 |

## What the reference does better than the cloud-only audit assumed

- Hypotheses in `crimpd-reference`/wave-1 notes that held: Add to Plan exists; plan by weeks; week stepper; Today block on the plans list; Logbook calendar/month; Edit/Clone/Delete on a log card.
- Hypotheses corrected by observation: (a) **days are not chosen when a workout is added to a plan** — they are chosen afterwards, per week, in the Schedule modal (the historical «day picker on Add-to-Plan» was wrong); (b) the reference has **no cross-week move**; (c) **no confirmations** on destructive plan edits; (d) the reference shows **estimated**, not measured, durations; (e) plan progress is **derived** from logs, so deleting a log immediately un-credits the plan.

## What ours does better — keep

Per-row «Перенести» across weeks; inline confirmation on remove; reload-resume of a live session; refusal of future-dated logs; explicit early-finish dialog; spec-driven duration rule.
