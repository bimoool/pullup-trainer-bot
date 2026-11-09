# PR #372 release checkpoint, 2026-11-09

Candidate: `781124c85a7c3bc63749730e44332e39f9f5dba5`.
Requested starting candidate: `ba5002bacd63cd485885fed64202b12b0da7f301`.
The final candidate fixes the date-dependent onboarding regression test and adds
month/year boundary cases. Runtime files are unchanged between these candidates.

## Verified gates

- Exact-candidate checks: all 15 checks passed. Backend: 3079 passed, 1 skipped
  on each of two runs; browser suite: 8 peer tests and 595 passed, 9 skipped.
- Guarded staging preflight: [42571972576](https://github.com/bimoool/pullup-trainer-bot/actions/runs/42571972576).
- Guarded staging deployment: [42576049000](https://github.com/bimoool/pullup-trainer-bot/actions/runs/42576049000), success.
  Exact candidate deployed; app/web healthy and image IDs matched the build.
  Backup checksum and restore check passed; previous images retained.
- Bot identity independently checked through Telegram `getMe`: `@fittest111_bot`;
  staging database name checked separately. No real-user QA identities used.
- Chromium staging QA: [42577330884](https://github.com/bimoool/pullup-trainer-bot/actions/runs/42577330884), 3 passed.
  Tests check all 10 sets of 5, authoritative 60-second inter-set rest durations,
  strength load +10 kg, technique-stop confirmation, early-finish cancellation
  and confirmation, and exactly one saved journal entry. Rest timers are skipped
  after checking their server duration and visible countdown, rather than waiting
  a full minute each time. Telegram popup transport uses a browser confirmation;
  the deployed API and workout engine are real.
- Production read-only preflight: [42577484802](https://github.com/bimoool/pullup-trainer-bot/actions/runs/42577484802), success.
  The first attempt safely refused because the candidate was absent from the
  server Git object cache; fetching the public commit fixed that prerequisite
  without changing the checked-out production revision or running services.
- iPhone WebKit staging QA: [42577638365](https://github.com/bimoool/pullup-trainer-bot/actions/runs/42577638365),
  3 passed without retries. The same three synthetic scenarios passed in both
  browser projects; this is browser emulation, not a native Telegram phone test.

## Pending release gate

Production remains on `4deb6457c4672fdb9c8b3146d6a40fddc75a1684`.
No production apply, manual user-record repair, or new token creation occurred.
The required isolated fresh production-copy rehearsal and rollback rehearsal
remain outstanding. The VPS cannot meet the rehearsal memory guard; it was not
lowered. A private local Linux environment is prepared, but transferring the
production dump requires separate owner approval. No dump was transferred.

Next task: if the owner authorizes the private copy, run the exact-candidate
rehearsal and rollback, remove the private copy,
install the reviewed guarded runner, and execute protected production apply with
its own verified backup and rollback manifest. Any failed gate blocks apply.
