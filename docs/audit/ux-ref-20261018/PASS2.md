# Pass 2 — rechecks, missing states, corrections (2026-10-18)

Scope: our product only (reference blocked). Every pass-1 P1/P2 item was re-run on an **independent new user**
(8800201 / 8800203, clean stand) or a different seeded profile; missing states from the gate's step 4 were added.

## Rechecks

| Item | Pass 2 result | Evidence |
|---|---|---|
| UX-01 plan row «Не успеть» + dead-end «Начать» | CONFIRMED on new user after one main session | `p2-b.log` (`UX-01 plan row`) |
| UX-03 duration 0:00 | CONFIRMED (≈40 s early-finish session → detail «0:00», summary without duration) | `p2-b.log` |
| UX-04 Journal vs Analytics totals | CONFIRMED after a second session and an edit (Journal 60+42, Analytics 95) | `p2-c-j10.log` |
| UX-05 onboarding max not in Tests | CONFIRMED on new user before any workout | `p2-recheck.log` |
| UX-06 no next step after «Добавить в план» | CONFIRMED | `p2-recheck.log` |
| UX-18 dark theme | NARROWED: in-app «Тёмная» override is readable; only Telegram-dark with empty themeParams breaks | `p2-theme-*` |
| E12 empty custom workout → plan | WITHDRAWN (editor disables the button) | `p2-e12.log` |

## Missing states added

| State | Result | Evidence |
|---|---|---|
| Reload during rest of a live set | resumes the same set and running rest timer (3:58) | `p2-recheck.log` (`STATE reload mid-live`) |
| «Завершить» mid-session | explicit dialog: what is saved, plan credit, no progression recalculation; «Сохранить и завершить / Назад / Отменить тренировку» | `p2-recheck-early-finish-full.png` |
| J10 set-value edit | Journal and Analytics converge | `p2-c-j10.log` |
| J8 with no own workouts | form offers «Сохранить» with nothing selectable → **UX-23** | `p2-b.log` |
| Legacy course record delete | native `confirm` + destructive recalculation → **UX-15** | `p2-legacy.log` |
| Narrow 320, light/dark, all tabs | no horizontal overflow; one 42 px target («Создать тренировку») | `p1-narrow` logs, `p1-n320-*` |

## Not covered (and why)

- **Reference side of every journey** — no access (single blocker, `INVENTORY.md`).
- Real Telegram chrome (BackButton/MainButton, closing confirmation), iOS safe-area/keyboard — needs device (`docs/IPHONE_QA_CHECKLIST.md`).
- Paid/expired access states, subscription flow, bot notifications — out of this UX pass; covered by existing tests.
- Coins/achievements values — v2 coins are a known non-working debt (CLAUDE.md); not assessed.
- Dedupe: UX-20 is a consequence of UX-01; UX-08 depends on UX-09 wording; UX-11 kept P3 until the reference shows whether a «today» block is expected.

## Result

22 open items: 4 × P1 (UX-15 needs the owner), 9 × P2 (UX-05 and UX-07 need the owner), 9 × P3; 1 withdrawn; 8 journeys/states passing.
Reference-independent correctness (UX-01–04, 23) can be fixed on spec grounds alone; layout/wording items
(UX-06, 08, 10–13, 16) need the reference observation before the final design.
