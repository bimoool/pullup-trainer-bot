# Local session checkpoint 1 — 2026-10-18

Model: Sonnet 5.5 (claude-sonnet-5-5).
Branch: `audit/ux-reference-local-20261018` (from `origin/audit/ux-reference-20261018` @ f6affcc). Rules: PR #340 @ 2cff870 (read).

## Access (verified this session)
| Item | Status | Evidence |
|---|---|---|
| Android emulator `ref_pixel6_play` (arm64, Play image) | AVAILABLE | booted, `adb devices` → emulator-5554 |
| Crimpd 8.5.3 (8050300), Play-installed | AVAILABLE | `dumpsys package`: versionName=8.5.3, installer=com.android.vending; launches to Home (`screens/chk_launch.png` in ~/android-ref-lab) |
| Control | adb + uiautomator + `texts.sh` (app = one WebView) | `~/android-ref-lab/RECIPE.md` |
| Prior local materials | FOUND (outside git) | `~/android-ref-lab/` screens (190), dumps, FLOW_INDEX, REF_MAP, SCREEN_INDEX, TEST_DATA_LEDGER, audit_* shots incl. plan/player/log flows |
| Our product | local build per cloud INVENTORY | not yet started locally |

Not used as evidence: Crimpd website, notes. Older 8.4.0 sideload does not pass licence gate; 8.5.3 does.

## Data-safety note
The emulator's Crimpd holds a signed-in account with pre-existing data (22 custom workouts, 166 log entries, 1 plan in progress).
Rule for pass: additive only, every object prefixed `REF TEST`, logged in TEST_DATA_LEDGER, deleted afterwards; existing items opened read-only.

## Scope / estimate
Reference journeys: plan create, add workouts, same-day repeat, week distribution, move/delete, execute, history (~8 flows × 2 passes).
Est. 4–6 h active (emulator is slow, ~10 s per screen). Then backlog merge (UX-NN ids kept), pass 2, decisions list, sprint rebuild.
