# Default v2 completion/navigation QA — 2026-11-10

Tracking: [#388](https://github.com/bimoool/pullup-trainer-bot/issues/388).
Reference: owner-provided [Crimpd report PR #385](https://github.com/bimoool/pullup-trainer-bot/pull/385)
at `f3249da407025dc6d68114cb16cf1ce1394ea239`, C05 (custom reps/timed last-set
DONE, dismiss review, no history entry). This evidence raises a product decision;
these tests preserve our accepted behavior, not Crimpd's save semantics.

Our contract is [LIVE_ENGINE_V2 §9.7](domain/LIVE_ENGINE_V2.md): natural COMPLETE
writes the session before optional effort/comment review. Custom Builder content
here has no course CONFIRM phase. This does not establish completion before
mandatory program checks, or decide explicit-save/miniplayer changes.

## Inventory and actual gap

- `session-summary-exit.spec.ts` and `session-back-button.spec.ts` explicitly force
  engine v1; they do not establish current default-v2 navigation behavior.
- Existing `live-engine-v2.spec.ts` scenarios 3/6 reached natural completion and
  clicked Save. They did not leave optional review unsaved and reopen history.
- `test_t_completion_retry_never_duplicates_progression_or_credit` in
  `tests/test_web/test_v2_live_engine.py` already proves v2 course completion,
  retry idempotency, one explicit credit and one progression revision.
- `test_queued_review_after_server_auto_completion_is_saved` and
  `test_redrained_completing_queue_never_duplicates_sets_completion_or_credit`
  in `test_v2_live_engine_offline_reopen.py` already protect server projection,
  later optional review, and duplicate event drains. No duplicate API test added.

Existing UI scenarios 2/3 now assert the actual start response has
`engine_version = 2`. Scenario 2 dismisses early-finish review through Telegram
Back and the sheet's Back, retains unsubmitted reps/note, and reads the same
active session with its recorded first set, no credit and no completed history. It then naturally completes reps 5,4.
Scenario 3 naturally completes reps 3 followed by a five-second timed set.
Both leave inline review through Telegram Back without Save, reload, and reopen
Journal details. Before leaving and after both reopen steps, public API reads
assert exactly one history row, exact numeric set facts, one plan completion,
the explicit session/plan credit link, no active session, and identical saved
results/revision/duration. Journal details independently show `Факт: 3` and
`Факт: 0:05` for scenario 3; this retains the prior numeric result coverage in
the reopened UI rather than weakening it to an exercise-name check.

The timer comparison waits for the existing event queue to drain before reading
the server: optimistic REST can otherwise be compared to the previous WORK
state, whose deadline is null.

## Validation and limits

Local browser runs use real built React, FastAPI and PostgreSQL with only
synthetic `live_engine` seeds 930602/930603 in an independently created
`pullup_v2_contract_e2e` database; owned API port 58012. Existing fixtures stub
`telegram.org/js/telegram-web-app.js`, supply signed synthetic launch data and
simulate Telegram BackButton events. The repository Playwright config was used
with a temporary local override selecting `/usr/bin/chromium`; selection was
`--project=chromium live-engine-v2.spec.ts --grep '2\. REST|3\. Отдых' --workers=1`.
No new API/SDK mocks or response fixtures
were added. This is functional Chromium/mobile-viewport coverage, not a real
Telegram client, official SDK integration, physical iPhone, or production check.

- Final focused Playwright scenarios 2/3: **2 passed (33.0s)**.
- Controlled mutation: temporarily skip canonical `_complete` for `FX_COMPLETED`
  in `app/services/live_engine.py`, restart the owned API, reseed and run scenario
  3. It fails at the new history assertion: expected `[sessionId]`, received `[]`.
  Restore the product file byte-for-byte, restart/reseed, and both cases pass.
  No product mutation is committed.
- Focused existing API integration suites (`test_v2_live_engine.py` and
  `test_v2_live_engine_offline_reopen.py`) on the same owned synthetic database,
  after the browser run: **29 passed, 1 deprecation warning (21.19s)**.
- Frontend `npm run build` (including application `tsc -b`): passed.
- `ruff check app/ tests/ scripts/`: passed; `git diff --check`: passed.
- Standalone E2E `tsc --project e2e/tsconfig.json --noEmit` remains blocked by the
  same seven unrelated diagnostics on unchanged HEAD and this change (normalized
  checkout-relative paths compare identically):

| File/line | Existing diagnostic |
| --- | --- |
| `audit-7500c37-fixes.spec.ts:104` | TS2488: NodeList lacks iterator |
| `live-engine-narrow.spec.ts:31` | TS2488: NodeList lacks iterator |
| `live-engine-narrow.spec.ts:132` | TS2488: NodeList lacks iterator |
| `parity/a11y-followup.spec.ts:76` | TS2339: Node has no remove |
| `parity/analytics-distribution.spec.ts:84` | TS2488: NodeList lacks iterator |
| `parity/background-timer.spec.ts:59` | TS2551: EventTarget has no release |
| `parity/visual-home-detail.spec.ts:36` | TS2488: NodeList lacks iterator |

Full CI remains separate from these focused local checks. No workflow, product,
formula, schema, migration, production history or server deployment changed.
