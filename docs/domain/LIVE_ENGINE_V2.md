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
