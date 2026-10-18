# Pass 2 — local session (reference + ours)

Second look at everything found in pass 1 of this session and at the cloud findings that the reference could
confirm or change. Focus (gate step 4): missing states, back, cancel, reopen, dependencies between screens.

## Reference side (real Crimpd) — rechecks and missing states

| Check | Result | Evidence |
|---|---|---|
| **Reopen:** leave the plan editor, reopen the plan | volumes, phases and schedule persisted | `p1_29`–`p1_35` |
| **Back/Cancel** inside forms: plan form, goal editor, Weekly Volume, Schedule, date picker, Log form | Cancel/Back never saves; hardware Back from a picker closed picker **and** the form (one level too far) | `p1_41`, `p2_01`–`p2_04` |
| **Dependency plan ↔ history** | logging in the plan's week credits the card/ring; deleting the log reverts both immediately | `p1_51`–`p1_62` |
| **Kill app mid-set** | Home on relaunch, no resume, no partial log | `p2_03`, `p2_04` |
| **Future weeks** of the active plan | week 5 Schedule opens; unscheduled items under «THIS WEEK» | `p2_07`–`p2_09` |
| **Empty states** | Upcoming empty text + CTA; week «No workouts planned for this week. Enjoy the rest!»; Today «No workouts scheduled for today» | `p1_78`, `p1_80`, `p1_01` |
| **Corrected after recheck** | first notes said «tap on a day toggles»; recheck with quantity 2 showed a **0→1→2→0 cycle**, and with 0.5 remaining a tap places 0.5 | `p1_31`–`p1_34`, `p1_43`–`p1_44` |
| **Near-miss (process finding)** | a navigation stack left the plan detail open, so one planned search tap landed on the **owner's** active plan screen. No Save was pressed; verified afterwards (Week 4 of 6 · 0/7, Upcoming empty, Logbook unchanged). Lesson: always return to a tab root before searching | `notes-raw.md` P2-10 |

## Our side — local stand (isolated)

| Check | Result | Evidence |
|---|---|---|
| Same workout twice in one day | OK, no collision error; two rows, no «×2» → UX-25 | `l3-01-after-add-Пн.png` |
| Add via workout detail vs weekly builder | different semantics (current week only vs whole plan) → UX-24 | `l3`, `l5` |
| Row actions | current-week rows without «⋯»; future rows with it → UX-31 | `l4`, `l5-03`, `l6-01` |
| Move: all weeks/days offered, saved by PATCH, past day accepted | → UX-31 | `l6`, `l7.log` |
| Remove: inline confirm | OK (kept) → UX-28 | `l6-05-remove-confirm.png` |
| Reload after changes | plan persists (week 2 identical after reload) | `l7.log` |
| Escape on Move screen | does nothing; no visible Cancel (native BackButton not available in harness — UNKNOWN in client) | `l7.log` |
| Re-verification of cloud P1/P2 items on the local stand | **not re-run** (UX-01–04 need a course session; they were reproduced on independent users in the cloud pass-2). They remain CONFIRMED by that evidence | `PASS2.md` |

## Changes to earlier findings

- UX-11 downgraded: the reference also has a «Today» block (on the plans list).
- UX-12, 13, 14, 16, 23 strengthened by reference evidence.
- UX-15 reclassified from NEEDS-OWNER to DECIDED (see `DECISIONS.md`); only the confirm dialog and card format remain.
- UX-05 reclassified: semantics decided, presentation default Q1.
- Historical wave-1 claim «day picker on Add-to-Plan» is **wrong** for the reference (days are scheduled afterwards per week).

## Not covered (and why)

- Reference first run/onboarding (account already onboarded); Skill Templates flow; result screen of «Add To Training Plan» (would change the owner's plan); Crimpd+ gating.
- Real Telegram chrome and iOS/Android WebView behaviour for our side (needs a device, `docs/IPHONE_QA_CHECKLIST.md`).
- Reference: fractional-quantity semantics, past-day rules in the schedule.
