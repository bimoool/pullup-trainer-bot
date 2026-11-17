# Default v2 completion/navigation QA — refreshed 2026-11-17

Tracking: [#388](https://github.com/bimoool/pullup-trainer-bot/issues/388),
existing [PR #389](https://github.com/bimoool/pullup-trainer-bot/pull/389).
Reference: owner-provided [Crimpd report PR #385](https://github.com/bimoool/pullup-trainer-bot/pull/385)
at `f3249da407025dc6d68114cb16cf1ce1394ea239`, C05 (custom reps/timed last-set
DONE, dismiss review, no history entry). These tests preserve our accepted
behavior; changing to Crimpd's explicit-save semantics remains a product decision.

Our contract is [LIVE_ENGINE_V2 §9.7](domain/LIVE_ENGINE_V2.md): natural COMPLETE
writes the session before optional effort/comment review. Custom Builder content
here has no course CONFIRM phase. This does not establish completion before
mandatory program checks, or decide explicit-save/miniplayer changes.

## Inventory and actual gap

The gap was rechecked against current `main` `869cd0d19334e59e5c0fb6d7cd280da3c095d4a9`:

- `session-summary-exit.spec.ts` and `session-back-button.spec.ts` explicitly force
  engine v1; they do not establish current default-v2 navigation behavior.
- Existing `live-engine-v2.spec.ts` scenarios 3/6 reach natural completion and
  click Save. Scenario 2 stops at the second WORK phase. They do not leave
  optional review unsaved and reopen history.
- `test_t_completion_retry_never_duplicates_progression_or_credit` in
  `tests/test_web/test_v2_live_engine.py` already proves v2 course completion,
  retry idempotency, one explicit credit and one progression revision.
- `test_queued_review_after_server_auto_completion_is_saved` and
  `test_redrained_completing_queue_never_duplicates_sets_completion_or_credit`
  in `test_v2_live_engine_offline_reopen.py` already protect server projection,
  later optional review, and duplicate event drains. No duplicate API test added.

PR #389's existing UI scenarios 2/3 assert the actual start response has
`engine_version = 2`. Scenario 2 dismisses early-finish review through Telegram
Back and the sheet's Back, retains unsubmitted reps/note, and reads the same
active session with its recorded first set, no credit and no completed history.
It then naturally completes reps 5,4. Scenario 3 naturally completes reps 3
followed by a five-second timed set.
Both leave inline review through Telegram Back without Save, reload, and reopen
Journal details. Before leaving and after both reopen steps, public API reads
assert exactly one history row, exact numeric set facts, one plan completion,
the explicit session/plan credit link, no active session, and identical saved
results/revision/duration. Journal details independently show `Факт: 3` and
`Факт: 0:05` for scenario 3; this retains numeric result coverage in the reopened UI.

The timer comparison waits for the existing event queue to drain before reading
the server: optimistic REST can otherwise be compared to the previous WORK
state, whose deadline is null.

## Current validation — 2026-11-17

The original branch/head `e861b4d17b972238433aa6b88c113c69d174aa1f` was continued.
Reviewed toolchain prerequisite PR #418 `0e15ba8` (including PR #390's E2E
typecheck fixes and current main) was included by normal merge. Combined code
checkpoint: `a3b61fabe7e6265fe5fc008309e50e336ba169b5`. No test assertion or
fixture change was needed for the refresh; prerequisite calendar fixtures and
event-queue durability changes remain intact. Integration order is #390, #418,
then #389, after each candidate's current required gates and independent review.

- Focused Chromium/mobile-viewport scenarios 2/3: **2 passed (32.7s)**.
- Frontend `npm run build` (application `tsc -b` and Vite 6.4.6): passed.
- Functional E2E `npm --prefix e2e run typecheck`: passed, **0 diagnostics**.
  The seven diagnostics documented on the original branch are resolved by #390.
- `git diff --check`: passed.

The browser run used real built React, FastAPI and PostgreSQL with synthetic
`live_engine` seeds 930602/930603 in a newly created owned database
`pullup_v2_completion_389_refresh`; owned API port 58039. Only that database
was migrated/seeded. The owned worktree's `dist` was built using read-only
shared dependency symlinks; no shared build output or dependency installation
was modified. The repository Playwright config had a temporary local override
selecting `/usr/bin/chromium`; selection was
`--project=chromium live-engine-v2.spec.ts --grep '2\. REST|3\. Отдых' --workers=1`.

Existing fixtures stub `telegram.org/js/telegram-web-app.js`, supply signed
synthetic launch data and simulate Telegram BackButton events. All product
APIs and persistence are real; no new API/SDK mocks or response fixtures were
added. This is functional Chromium/mobile-viewport coverage, not a real
Telegram client, official SDK integration, physical iPhone, or production check.

Full mandatory hosted CI must run on the final published head; the focused
checks above and historical results below do not replace it. This task does not
merge or deploy. Relative to the reviewed prerequisite, only this QA document
and `live-engine-v2.spec.ts` differ; product, schema and workflows are unchanged.

## Historical evidence — original 2026-11-10 checkpoint only

- Focused Playwright scenarios 2/3: **2 passed (33.0s)**.
- Controlled mutation: temporarily skip canonical `_complete` for `FX_COMPLETED`
  in `app/services/live_engine.py`, restart the owned API, reseed and run scenario
  3. It failed at the new history assertion: expected `[sessionId]`, received `[]`.
  Restoring the product file byte-for-byte, restarting/reseeding made both pass.
  This mutation was not repeated on the refreshed combined head; no product
  mutation is committed.
- Existing API integration suites (`test_v2_live_engine.py` and
  `test_v2_live_engine_offline_reopen.py`): **29 passed, 1 deprecation warning
  (21.19s)**. These were not rerun for the test/docs-only refresh.
- Frontend build, Ruff and diff whitespace checks passed on that checkpoint.
