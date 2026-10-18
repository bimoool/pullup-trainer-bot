# REF-2 TEST DATA LEDGER
Initial snapshot: dumps/r2_INITIAL_home_full.txt (Home DOM: 9 category cards, 6 playlists, My Workouts (Russian names, 22 cards), Favorite Workouts (14), 10 Assessments)
| type | visible name | created | id | where | deleted |
|---|---|---|---|---|---|
(none yet)
| custom workout | REF TEST - Custom Workout (ASCII hyphen; em dash could not be typed via adb) | 2026-09-29 ~14:00 local (emulator ~1:57pm) | none visible | Home + > Create Custom Workout > Fingerboard Workout > Dead Hang: 20mm Edge 3 sets x1 rep > Strength & Power / Finger Strength (Save tapped now) | pending |
| logbook entry | log of "REF TEST - Custom Workout" (3 sets x1 rep, Easy) dated 29 Sep 2026 | ~2:02pm emulator time | none visible | saved from player-finish Log Workout form | pending (delete via Logbook sheet > Delete Log, verify name first) |
| (update) logbook entry above | REF TEST - Custom Workout log | DELETED ~2:05pm via Logbook sheet (title verified) > Delete Log > confirm | | | deleted; Logbook DOM diff vs initial snapshot = identical (166 entries) |
| (update) custom workout | REF TEST - Custom Workout | DELETED ~2:15pm: Search "REF TEST" > detail > pencil > Edit Workout (name verified) > Delete Workout; toast "Successfully deleted workout"; no confirm dialog observed | | | deleted |
| (temp toggle) favorite | Favorite heart on REF TEST workout toggled on then off (2:08pm) | | | | reverted; workout later deleted |

## FINAL SAFETY PASS (2:15pm)
- Home full DOM diff (initial vs final): IDENTICAL (My Workouts, Favorites, playlists, assessments, category counts).
- Logbook DOM diff (166 entries): IDENTICAL after deleting the REF TEST log.
- Plans Completed list: IDENTICAL; In Progress plan unchanged (opened read-only, only Cancel used on its menu).
- Analytics S&P 21/442/32/10 -> 22/446/32/11 while log existed -> back to 21/442/32/10 after delete.
- Remaining REF TEST objects: NONE. No custom exercises created ("Create Exercise: Zzqx" row observed, not tapped).
- Side effects: notification permission dialog declined ("Don't allow") once; app process force-stopped/relaunched twice.
| logbook entry | log of '1 On 1 Off' dated 2 Nov 2026, saved from Log Workout (plan credit test) | 2026-10-18 ~15:01 emu | | Logbook | pending delete |
| logbook entry | 1 On 1 Off live-session log dated 18 Oct 2026 (player->clipboard->Save) | emu 3:03pm | | Logbook | pending delete |
(update) both 1 On 1 Off logs deleted 15:05 emu
(update) REF TEST Plan DELETED (confirm sheet 'Are you sure you want to delete this training plan?'); Upcoming empty; owner plan untouched
