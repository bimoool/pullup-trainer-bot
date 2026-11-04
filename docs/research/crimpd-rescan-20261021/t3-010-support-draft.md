# Черновик обращения в поддержку Crimpd (НЕ отправлено; отправка — только владельцем)

**Subject:** Max Hangs (85/90/95%) tabs A and B keep showing values from a deleted test result; tab C is correct

Hello,

After I created and deleted temporary Finger Strength Test results, the load shown on tabs A (85%) and B (90%) of the "Max Hangs" workouts did not return to the values computed from my real latest result. Tab C (95%) recalculated correctly.

**App / device:** Crimpd 8.5.3 (build 8050300), Android 14 emulator (Pixel 6 profile). Body weight 70 kg.
**Real data (unchanged):** Finger Strength Test, latest result July 23, 2026: +40 kg (157.1% of body weight).

**Sequence (dates in 2026):**
1. Baseline, Oct 24: Max Hangs 85% / 90% / 95% showed A +24 kg, B +29 kg, C +35 kg (matches 0.85/0.90/0.95 × (70+40) − 70).
2. Oct 26: logged a temporary Finger Strength Test result of +10 kg (dated Aug 5, i.e. earlier than the real result). Max Hangs tabs then showed A −2, B +2, C +6 (matches the formula for +10).
3. Logged and edited further temporary Finger Strength Test results (+40 → +20 on Aug 5; +40 on Sep 1), then deleted all temporary results (via Edit Workout Log → Delete Log). Profile and Test History again show only the real history (latest July 23, +40 kg); no October entry.
4. After deletion: tab C = +35 (correct), but tab A = −2 and tab B = +2 (the values for the deleted +10 result).
5. The same values persist after: cold restart (force stop + launch), changing and restoring body weight, creating/deleting other test logs, another test, page refresh, and after sign-out / sign-in again (Oct 27, 13:12), and after another cold restart (13:18).

**Expected:** A +24, B +29, C +35 kg.
**Actual:** A −2, B +2, C +35 kg (identical in the Max Hangs 85%, 90% and 95% workout pages).

A similar display mismatch on another workout (Max Hangs – One Arm) resolved itself within 1–3 days earlier in October; this one has not after more than a day.

Questions: where are the A/B loads computed from, can they be recalculated from the current test history, and is this a known issue? No real results were modified; I can send screenshots.

Thank you.
