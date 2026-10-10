# LIVE_ENGINE_V2 — execution state machine (contract, not implementation)

Index: [README.md](README.md). Input: a `PrescriptionSnapshot` ([WORKOUT_DOMAIN_V2.md §5](WORKOUT_DOMAIN_V2.md#5-versions-and-snapshots)).
Output: a completed/cancelled `TrainingSession` ([TRAINING_SESSION_V2.md](TRAINING_SESSION_V2.md)).
Supersedes `PROJECT_SPEC.md` §2 items 5 (manual «Начать» between blocks), 13 (client-only pause)
and the «Фон/блокировка» rule “переход — только действие пользователя” once Wave 2 lands.

## 1. State

```
EngineState (persisted on training_sessions; engine_version = 2)
  status            active | completed | cancelled
  cursor            { block_index, set_index, round_index }
  phase             PREP | WORK | RESULT | REST | COMPLETE        (§3)
  phase_started_at  UTC ts
  phase_deadline_at UTC ts | null     null ⇔ phase waits for the user (WORK of reps/max, RESULT)
  paused_at         UTC ts | null     orthogonal flag: any timed phase can be paused
  paused_remaining_ms int | null
  phase_seq         int, +1 on every transition (compare-and-set token; replaces phase_index)
  active_elapsed_ms int               excludes paused time; becomes session duration
```

Every transition is appended to `session_events` (append-only:
`session_id, seq, client_event_id UNIQUE, type, payload, client_at, server_at`). Engine state is a
cache of folding these events; rebuilding from events must give the same state (test).

## 2. One authoritative clock

- **C1** The only countdown input is `phase_deadline_at` (absolute UTC) issued by the server
  engine. Remaining = `deadline − (Date.now() + server_offset)`, where `server_offset` is learned
  from `server_time` on every response (same technique as `IntervalLiveScreen.tsx:70`, now for
  every phase).
- **C2** The client keeps **no** duration constants (no local 5/90) and no second
  `setInterval`-driven decrement. A single render tick (rAF/1 s) *reads* the deadline; audio and
  vibration are scheduled from the same deadline (§6), not from their own timers.
- **C3** Transitions are one pure function shared by contract: `advance(state, event, at) →
  (state', emitted_events)`, implemented in `app/domain/` and mirrored in TypeScript **from the
  same test vectors** (JSON fixtures consumed by pytest and vitest). The client never invents a
  transition the server would not make.
- **C4** Offline: the client appends events locally with `client_event_id` and `client_at`, renders
  `project(state, now)`, and flushes in order. The server replays them through `advance` using
  `client_at` clamped to `[last_server_at, now]`. A replayed event whose `phase_seq` is stale is a
  no-op (idempotent), never a 409.

## 3. Phases and transitions

| From | Trigger | To | Auto? |
|---|---|---|---|
| (start) | `start` | PREP if `block.prep_seconds > 0` else WORK | — |
| PREP | deadline | WORK | **auto** |
| WORK (`time`, interval work) | deadline | RESULT if correction/round-reps enabled, else REST/next | **auto** |
| WORK (`reps`, `max_reps`) | `submit_result(value)` | REST / next block / COMPLETE | user |
| WORK (`max_time`) | `stop` | RESULT (measured, editable) | user |
| RESULT | `submit_result` **or** next deadline reached (value = default) | REST / next | user or auto |
| REST (after set) | deadline | WORK of next set (no PREP) | **auto** |
| REST (after block) | deadline | PREP of next block (if `prep_seconds>0`) else WORK | **auto** |
| any timed | `pause` / `resume` | same phase, deadline frozen / re-issued | user |
| any | `finish_early` | COMPLETE | user |
| any | `cancel` | (cancelled) | user |
| after last prescribed set of a block (`extra_sets_allowed`) | `add_extra_set` | WORK(extra) → RESULT → back to where it was | user |
| WORK/RESULT of set n | `correct_previous(n-1, value)` | same phase (edits the log only) | user |

Next-step rule (pure): after a set, if `rest_after_seconds` non-null → REST; else if more blocks
→ REST(after block) if `rest_after_block_seconds` else PREP/WORK of next block; else COMPLETE.

- **T1** No mandatory confirmation exists for a deterministic transition: PREP and REST have no
  «Готов»/«Пропустить отдых» primary button (D4). A secondary «Начать сейчас» MAY be shown; it is
  the event `skip_wait`, equivalent to reaching the deadline now.
- **T2** Block transitions are automatic (block rest shows the next exercise as preview). This
  replaces the manual Builder interstitial of `PROJECT_SPEC.md` §2.5.
- **T3** RESULT for `time` sets auto-accepts the default at the next deadline, so a timed workout
  runs hands-free from start to COMPLETE.
- **T4** `finish_early`: performed sets are kept, unperformed prescribed sets are recorded as
  `not_performed`; the session is a normal completed session (journal, analytics, plan credit per
  [PROGRAM_PLAN_V2.md §5](PROGRAM_PLAN_V2.md#5-plan-planweek-planitem-completion-credit); progression decides
  from what was performed).
- **T5** `cancel`: status `cancelled`; no journal entry, no analytics, no plan credit, no
  progression; the row is retained (archive, not delete).
- **T6** Extra sets: `SetLog.is_extra = true`, never advance prescribed cursor, never count toward
  plan credit or progression (existing rule kept, now in the engine).

## 4. Manual entry vs automatic progression

| Workout type | Runs hands-free? | User input |
|---|---|---|
| Only `time` sets / intervals without round reps | yes | optional corrections |
| Interval with `record_reps_per_round` | yes (clock) | reps per round, may be entered during the following rest or after COMPLETE |
| Any `reps`/`max_reps` set | no | value per set (WORK ends on submit) |
| `max_time` | no | stop |

## 5. Pause, background, resume

- **P1** Pause is a **server event** (queued offline like any other): `paused_remaining_ms =
  deadline − at`; `phase_deadline_at = null`. Resume: new deadline `= at + paused_remaining_ms`.
  Pause survives reload, device switch and phase sync (replaces client-only `pausedRemainingMs`).
- **P2** Untimed phases (WORK reps, RESULT) need no pause; `active_elapsed_ms` still excludes
  paused intervals for duration.
- **P3** Background/lock: the clock is real. On `visibilitychange → visible` (and on reload) the
  client renders `project(state, now)`: deterministic phases that expired in background have
  advanced, exactly as the server would (the server also projects lazily on every read and
  persists the projected transitions as `deadline` events with `server_at = deadline`).
  Projection **stops** at the first phase that waits for the user.
- **P4** Audio/vibration events are never emitted retroactively for transitions that happened
  while hidden; on return only future events are scheduled.
- **P5** Interval blocks follow the same engine (no separate screen state machine); pause is
  allowed for intervals too (the deadline is re-issued), which removes today’s exception.

## 6. Audio-event hooks (interface only; audio itself is not in Wave 0)

The engine exposes a pure `timeline(state) → [{type, at}]` for the current and next phase:

| type | at |
|---|---|
| `warn_10s` | deadline − 10 s (REST/PREP only, phases ≥ 15 s) |
| `count_3`, `count_2`, `count_1` | deadline − 3/2/1 s (PREP, REST, timed WORK) |
| `work_start` | WORK phase start |
| `work_end` | timed WORK deadline |
| `rest_end` | REST deadline |
| `workout_complete` | COMPLETE |

The UI audio layer subscribes to this list and (re)schedules after every state change, pause,
resume or visibility change. It owns no timers of its own.

## 7. Session start preconditions (server)

`start` is accepted only if: the snapshot is resolvable; access passes `ProgramAccessService`;
scheduling constraints pass ([PROGRAM_PLAN_V2.md §4](PROGRAM_PLAN_V2.md#4-scheduling-constraints-min-rest-days));
no other `active` session exists for the user (resume offered instead).
Errors are typed (`too_early{available_from}`, `subscription_required`, `active_session_exists`).

## 8. Compatibility

Sessions started under the current engine keep `engine_version = 1` and finish under it; only
new sessions use v2 (MIGRATION §6). The legacy v1 screen (`LiveWorkoutScreen.tsx`, `/api/workout/draft`)
is retired after Wave 4 acceptance, not modified.

## 9. Implementation decisions (Wave 2, #306)

Code: `app/domain/live_engine.py` (pure engine), `app/domain/live_engine_plan.py` (plan from snapshot),
`app/services/live_engine.py` (events, projection, effects), `app/web/routes_v2_live.py` (router split out of
`routes_v2.py`), `webapp-frontend/src/liveEngine.ts` (mirror), `webapp-frontend/src/LiveEngineScreen.tsx`.
Shared vectors: `contracts/live_engine_vectors.json` (pytest `tests/test_live_engine_vectors.py`, vitest
`webapp-frontend/tests/liveEngineVectors.vitest.ts`). Migration `a9e6c3d1f5b7`. None of these changes a rule above.

1. **Data shape.** Plan, state and events are plain JSON, time is integer UTC epoch ms — one representation for
   Python, TypeScript and the vectors. `advance(plan, state, event, at) → (state', effects)`: the plan is the
   immutable input built once at start (stored in `training_sessions.engine_plan`); `effects` are what the
   service persists (`set_logged`, `set_corrected`, `block_started`, `block_finished`, `completed`, `cancelled`).
   Rounding of measured seconds is half-up in integers (Python's `round()` is banker's).
2. **Engine selection.** `POST /sessions/live` takes `engine_version` (default 1). The current client sends 2;
   cached old bundles keep starting v1 sessions (MIGRATION §6). A v2 session refuses every v1 transition endpoint
   (`phase/next|back`, `blocks/start|finish`, `sets:batch`) with `409 engine_version_mismatch`; `POST /events` on a
   v1 session is the same 409. `POST …/complete` keeps the #307 interface for both (v2: server `finish_early`,
   then the idempotent `complete_session` fills effort/comment).
3. **Event API.** `POST /sessions/live/{id}/events {events: [{client_event_id, type, payload, client_at}]}`. Under
   the session row lock: duplicate `client_event_id` → `duplicate` (no new row, 200); `client_at` clamped to
   `[last_at, now]`; deadlines up to that moment are projected and persisted as `deadline` events
   (`server_at = deadline`); then the event (`applied` or `noop`, both stored — replay folds them identically);
   finally deadlines up to now. A `client_event_id` already used by another session → 422 (no disclosure);
   foreign session → 404. Only client event types are accepted (`start`/`deadline` are server-only).
4. **Staleness.** Control events (`skip_wait`, `pause`, `resume`, `stop`) carry `phase_seq` and are no-ops when it
   is stale. `phase_seq` grows on every phase change, not on pause/resume or log edits. Result events
   (`submit_result`) are addressed by cursor `{block_index, set_index, round_index}`, not by `phase_seq`: a set
   submitted offline is not lost to clock jitter at a PREP boundary (if the server is still in PREP of that same
   set, PREP ends at the event time). A result for a set the cursor already passed is a no-op.
5. **Set kinds.** `time`: at the WORK deadline the result is the target (T3, hands-free); `stop` ends it early with
   the measured active seconds; corrections via `correct_previous`. `max_time`: `stop` → RESULT with the measured
   value, waits for `submit_result`. Interval rounds: the round's WORK deadline logs the round; with
   `record_reps_per_round` the round rest is a RESULT phase that keeps the rest deadline (clock never stops,
   input optional; input turns the remainder into REST). A round without entered reps writes no `SetLog`
   (no fake «0 повт.»); the block's `result` JSON keeps `completed_cycles`.
6. **Extra sets** (`add_extra_set {block_index, value}`) are logged immediately and never change the phase — the
   table's `WORK(extra) → RESULT → back` collapsed into one event, as #264 already behaved. Allowed once the block's
   prescribed sets are all logged (block rest or later), including after COMPLETE of the last block.
   `correct_previous` targets an existing log; after completion it bumps `revision` (ED2).
7. **Completion.** COMPLETE is terminal and is written through `LiveSessionService.complete_session` (#307, the
   single writer) with `active_elapsed_ms` from the engine and `ended_at` = the engine's COMPLETE time (a
   background projection may complete the session before anyone reads it). `abandoned` = some prescribed set was
   not logged. The review (effort/comment) is a later idempotent `complete` call.
8. **Zero work and duration (#307 N2).** `finish_early` with no performed prescribed set is a cancel (T5): no
   journal entry, credit or duration — zero work never becomes a completed workout. `active_elapsed_ms` that
   rounds to 0 s, or exceeds 6 h (a session left open), gives `duration_source = unknown`, never a measured 0 and
   never an invented minute; short honest work (a 40 s plank) stays `measured`.
9. **Cancel (T5) without a new enum value.** `mp_session_status` is not extended (TRAINING_SESSION_V2 §11).
   `engine_status = cancelled` (CHECK-constrained string) marks the archived row; `status` stays `started`;
   `plan_item_id` is cleared (no plan credit). Active-session lookup and session lists exclude it.
10. **Plan source.** A v2 start of a Builder workout with a definition version builds `SetTarget` from the
    version's snapshot (the W-ladder executes as 17 sets, J3) and the engine plan 1:1 from it. Synthesized
    snapshots (STEP course blocks, legacy without a version) carry no rest/prep; the engine plan then uses the
    contract defaults (WORKOUT §3.2/§3.6/§9.1: rest 90 s or the V1 protocol's rest, block rest 90 s, prep 5 s for
    the first block and for blocks starting with a timed set or an interval). A V1 interval whose total is not a
    multiple of work + rest keeps V1's count of work rounds (`ceil(total / (work + rest))`; V1 15 s at 5/5 = two
    work phases).
11. **Projection on read (P3).** `GET /sessions/live/active` and the session list project due deadlines (same
    path as an empty events request) — the client returning from background sees the advanced state.
12. **Client.** `LiveEngineScreen` renders `project(fold(server.state, queue), Date.now() + offset)` with the
    mirror; the offset comes from `engine.server_time_ms` against the request midpoint. No duration constants, no
    `endsAtOverride`/`pausedRemainingMs`, no second timer. The offline queue lives in IndexedDB, one per session
    (`pullup:v2:live-engine-queue:<session_id>`, events + the pending review); any server response replaces the base
    state and drops acknowledged events. **Ordering (acceptance B1):** a stored queue is sent before any request that
    can project deadlines. Projecting endpoints: `GET /sessions/live/active`, `GET /sessions` (lazy projection of
    started sessions), and `POST …/events` / `POST …/complete` of a v2 session (the reconciliation itself and the open
    screen of that session). The app starts one reconciliation of all stored queues at launch, before its first screen
    (`startEngineReconciliation`), and again when the live screen closes and on `online`; a transient failure
    (network, 5xx, 408/429) keeps the queue and retries after 1, 2, 4, 8, 15, 15… s (woken early by `online` or the
    app becoming visible). While it runs, every client read of the two projecting GETs waits for it
    (`engineGate.ts`, awaited inside `fetchActiveLiveSession` / `fetchSessions` / `fetchSessionsPage`). A terminal
    answer (404/409 — the session is gone or is not v2) drops that queue; another 4xx keeps it without retrying. The
    open screen owns its session's queue (`claimQueue`), so the app-level drain skips it. User input made before a
    deadline therefore always reaches the server before that deadline is persisted; the server's rules (clamping,
    stale no-op, duplicate) are unchanged. The same drain sends a review queued for a session the server
    already completed by itself (no longer active, so no screen would reopen it). Audio: the engine exposes
    `timeline(state)` (and the response carries it); the screen schedules only the phase-end cue from the single
    deadline, never retroactively (P4). Sound assets are out of scope.
13. **Rollback switch (MIGRATION §8 "flags").** `localStorage["pullup:live-engine-version"] = "1"` makes the client
    start new sessions on engine v1 (server unchanged; running v2 sessions keep v2). E2E specs that assert the v1
    screen's own UX (it still serves `engine_version = 1` sessions until W4) pin it per file
    (`useLiveEngineV1(test)`); v2 behaviour is covered by `live-engine-v2.spec.ts` and the converted journeys.
