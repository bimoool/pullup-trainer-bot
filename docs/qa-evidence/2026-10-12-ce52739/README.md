# QA evidence — preliminary QA of `ce52739` vs integration `3758a88` (2026-10-12)

Status: **preliminary QA, not release acceptance.** Read-only session; nothing merged/deployed, ORCH stopped.
Issues #295–#301 are NOT closed by this: code fixes ≠ release acceptance and rollout.

- feature: `ce52739` (`wave1/course-prescription`, PR #314); base: `integration/domain-v2` @ `3758a88`
- CI run under comparison: 38169133912. CI logs/artifact were unreadable from the sandbox (proxy 403 on the
  Actions log/blob hosts), so CI failure texts are NOT here. Navigator has the CI numbers:
  `ce52739` 506 passed / 9 failed / 8 skipped; #318 502 / 17 / 8. Do not compare them 1:1 with the local counts below.

## How to get it
`git fetch origin claude/upbeat-knuth-btfucy` → `docs/qa-evidence/2026-10-12-ce52739/`
(branch is evidence-only on top of `main` `b06d572`; not meant to be merged). Contents: `README.md`,
`screenshots/` (17 PNG, synthetic users only), `logs/` (Playwright list output), `harness/` (the shell
drivers used). The scratch Playwright spec (`_scratch_qa.spec.ts`) is intentionally NOT committed.

## Reliable results
| Result | Evidence |
|---|---|
| Clean install (`alembic upgrade head` only) ships catalogue: 1 program (free), 14 exercises, 4 system workouts, 1 collection item, 3 protocols, 0 users; catalogue `frequency` still 3 | one deterministic run on fresh DB `qa_clean` |
| 99 pytest for #296–#301 (system content, plan items, future weeks, convergence, repair script, subscription gate) pass on `ce52739` | own pytest DB `pullup_test_qa` |
| The 19 tests (builder-execution, golden-journey, live-engine-v2) all pass on base AND feature, same settings, separate DBs | `logs/pw_base.log`, `logs/pw_feat.log` |
| Same 19 pass on both in the unloaded repeat | `logs/rep5_base_3.log`, `logs/rep5_feat_3.log` |
| `plans-start-session` passes on both after a clean reseed (id 900016) | run in session, 1 test each |
| Fresh-user UI path, background→return, reload mid-Live (no 2nd `POST /sessions/live`), server restart → Journal/Plans/Analytics persist | `screenshots/1_*`, `2_*`; J1 spec also passes on `qa_clean` |
| QA identities `qa_aged_active`/`qa_aged_legacy_snapshot` land on the V5.6 setup form instead of «Начать» (S-OWNER-01/02 fail) — harness drift, cause read from the page snapshot | local DB `qa_staging_feat` (name chosen so the staging guard passes; local only) |

Caveat: Chromium with a mocked Telegram WebApp, not real Telegram/Crimpd/iPhone.

## Contaminated runs (do not use as independent evidence)
| Run | Why |
|---|---|
| `logs/full_base_r1.log`, `logs/full_feat_r1.log` (full suite, CI=1, 1 worker) | Seeding was started twice per DB for a while (I relaunched `full.sh` while the first was still seeding, then killed the duplicates mid-way); a concurrent scratch Playwright run in the same `e2e/` dir cleared `test-results` (ENOENT trace errors); the feature run also picked up my scratch spec (failed on its default id); both suites ran at once (load ≈ 6). The 14 failures common to both trees (parity final-journey/full-sweep/sweep-defects, expired-course-gate) are therefore NOT a clean "base failure" proof; the feature-only `plans-start-session` failure was an artifact of this contamination (passes in isolation). |
| `logs/rep5_*_1.log`, `logs/rep5_*_2.log` | Deliberate CPU stress (4 busy loops, 1500 s timeout) plus base and feature running simultaneously; rep2 was only partly loaded. Shows load sensitivity only. |

## What the repeats do show (load sensitivity, not regression evidence)
- builder-execution C (standalone MAX): failed on **base** under partial load (rep2); passes unloaded on both.
- live-engine-v2 #10 and #11: same failure signature on base and feature under load (120 s waiting for a `Начать:` row in «Движок: стоп»); I did not establish why load removes that row.
- golden-journey and live-engine-v2 #4: not reproduced anywhere → unknown.

## Retained in the (ephemeral) container — gone when it is reclaimed
| Item | Why kept |
|---|---|
| `/home/user/wt-base` (detached `3758a88`, built `dist`, node_modules) | base side of the comparison |
| `/home/user/wt-feat` (detached `ce52739`, clean) | feature side |
| `/home/user/wt-evidence` (branch `claude/upbeat-knuth-btfucy`) | this evidence commit |
| `/home/user/pullup-trainer-bot` on `wave1/course-prescription` `deccf7b` (3 behind origin) | untouched primary checkout; no writes |
| Postgres DBs `qa_base`, `qa_feat` | e2e-seeded and mutated by the runs (post-run state) |
| `qa_clean` | fresh-user data: J1 user, phase1/2 user 7950002 |
| `qa_staging_feat` | provisioned QA identities + staging-spec state |
| `pullup_test_qa` | pytest database |
All uvicorn servers started for this QA are stopped; no one else's processes were touched.
The durable copy is the git branch above; DB contents are not exported.
