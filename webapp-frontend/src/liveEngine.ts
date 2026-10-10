/**
 * Live Engine v2 — TypeScript-зеркало app/domain/live_engine.py (issue #306, docs/domain/LIVE_ENGINE_V2.md §2 C3).
 *
 * НЕ вторая интерпретация: построчная копия той же чистой функции переходов. Обе реализации обязаны
 * проходить ОДНИ И ТЕ ЖЕ векторы `contracts/live_engine_vectors.json` (pytest + vitest). Любая правка
 * переходов — сначала вектор, потом обе стороны.
 *
 * Клиент НЕ решает переходы сам (C3): он рисует `project(state, now)` между ответами сервера
 * (фон/офлайн) и шлёт события; ответ сервера целиком заменяет локальную проекцию. Время — целые мс,
 * «сейчас» клиента = Date.now() + serverOffset (C1).
 */

export const ENGINE_VERSION = 2;

export type Phase = "PREP" | "WORK" | "RESULT" | "REST" | "COMPLETE";
export type EngineStatus = "active" | "completed" | "cancelled";
export type RestKind = "set" | "block" | "round" | null;

export type SetKind = "reps" | "max_reps" | "time" | "max_time";

export interface PlanSet {
  kind: SetKind;
  target: number | null;
  rest_after_seconds: number | null;
}

export interface PlanInterval {
  work_seconds: number;
  rest_seconds: number;
  rounds: number;
  record_reps_per_round: boolean;
}

export interface PlanBlock {
  kind: "sets" | "interval";
  prep_seconds: number;
  rest_after_block_seconds: number | null;
  extra_sets_allowed?: boolean;
  sets?: PlanSet[];
  interval?: PlanInterval;
}

export interface EnginePlan {
  blocks: PlanBlock[];
}

export interface Cursor {
  block_index: number;
  set_index: number;
  round_index: number | null;
}

export interface EngineLog {
  log_index: number;
  block_index: number;
  set_index: number;
  round_index: number | null;
  value: number | null;
  is_extra: boolean;
  effort: number | null;
  note: string | null;
  logged_at: number;
}

export interface EngineState {
  engine_version: number;
  status: EngineStatus;
  phase: Phase;
  cursor: Cursor;
  rest_kind: RestKind;
  phase_started_at: number;
  phase_duration_ms: number | null;
  phase_deadline_at: number | null;
  paused_at: number | null;
  paused_remaining_ms: number | null;
  phase_seq: number;
  active_elapsed_ms: number;
  active_since: number | null;
  phase_active_ms: number;
  pending_value: number | null;
  started_at: number;
  ended_at: number | null;
  last_at: number;
  block_started_at: number | null;
  logs: EngineLog[];
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Payload = Record<string, any>;

export interface EngineEvent {
  type: string;
  payload?: Payload;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Effect = Record<string, any>;

export interface TimelineCue {
  type: string;
  at: number;
}

const WARN_10S_MIN_PHASE_MS = 15_000;
const MAX_RESULT_VALUE = 99_999;

export class EngineError extends Error {}

// ============================================================================
// План
// ============================================================================

const isInt = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value);

export function validatePlan(plan: EnginePlan): void {
  const blocks = plan?.blocks;
  if (!Array.isArray(blocks) || blocks.length === 0) {
    throw new EngineError("plan.blocks: нужен хотя бы один блок");
  }
  blocks.forEach((block, index) => {
    if (!isInt(block.prep_seconds) || block.prep_seconds < 0) {
      throw new EngineError(`blocks[${index}].prep_seconds`);
    }
    const restBlock = block.rest_after_block_seconds;
    if (restBlock !== null && restBlock !== undefined && (!isInt(restBlock) || restBlock < 0)) {
      throw new EngineError(`blocks[${index}].rest_after_block_seconds`);
    }
    if (block.kind === "sets") {
      const sets = block.sets;
      if (!Array.isArray(sets) || sets.length === 0) {
        throw new EngineError(`blocks[${index}].sets: нужен хотя бы один подход`);
      }
      sets.forEach((set, setIndex) => {
        if (!["reps", "max_reps", "time", "max_time"].includes(set.kind)) {
          throw new EngineError(`blocks[${index}].sets[${setIndex}].kind`);
        }
        if (set.kind === "time" && (!isInt(set.target) || (set.target as number) < 1)) {
          throw new EngineError(`blocks[${index}].sets[${setIndex}].target`);
        }
        const rest = set.rest_after_seconds;
        if (rest !== null && rest !== undefined && (!isInt(rest) || rest < 0)) {
          throw new EngineError(`blocks[${index}].sets[${setIndex}].rest_after_seconds`);
        }
      });
    } else if (block.kind === "interval") {
      const interval = block.interval;
      if (!interval || !isInt(interval.work_seconds) || interval.work_seconds < 1) {
        throw new EngineError(`blocks[${index}].interval.work_seconds`);
      }
      if (!isInt(interval.rest_seconds) || interval.rest_seconds < 0) {
        throw new EngineError(`blocks[${index}].interval.rest_seconds`);
      }
      if (!isInt(interval.rounds) || interval.rounds < 1) {
        throw new EngineError(`blocks[${index}].interval.rounds`);
      }
    } else {
      throw new EngineError(`blocks[${index}].kind`);
    }
  });
}

const blockOf = (plan: EnginePlan, blockIndex: number): PlanBlock => plan.blocks[blockIndex];
const setSpec = (plan: EnginePlan, blockIndex: number, setIndex: number): PlanSet =>
  (plan.blocks[blockIndex].sets as PlanSet[])[setIndex];
const isIntervalBlock = (plan: EnginePlan, blockIndex: number): boolean => blockOf(plan, blockIndex).kind === "interval";

function prescribedCount(plan: EnginePlan, blockIndex: number): number {
  const block = blockOf(plan, blockIndex);
  return block.kind === "interval" ? (block.interval as PlanInterval).rounds : (block.sets as PlanSet[]).length;
}

// ============================================================================
// Время и учёт активной длительности
// ============================================================================

const msToSeconds = (ms: number): number => Math.floor((ms + 500) / 1000);

export function clampClientAt(clientAt: number | null, lastAt: number, now: number): number {
  if (clientAt === null || clientAt === undefined) {
    return Math.max(lastAt, now);
  }
  return now >= lastAt ? Math.max(lastAt, Math.min(Math.trunc(clientAt), now)) : lastAt;
}

function accrue(state: EngineState, at: number): void {
  const since = state.active_since;
  if (since !== null && at > since) {
    state.active_elapsed_ms += at - since;
    state.phase_active_ms += at - since;
  }
  if (since !== null) {
    state.active_since = Math.max(since, at);
  }
  state.last_at = Math.max(state.last_at, at);
}

function enterPhase(
  state: EngineState, phase: Phase, at: number, durationMs: number | null, blockIndex: number, setIndex: number,
  roundIndex: number | null, restKind: RestKind = null,
): void {
  state.phase = phase;
  state.cursor = { block_index: blockIndex, set_index: setIndex, round_index: roundIndex };
  state.rest_kind = restKind;
  state.phase_started_at = at;
  state.phase_duration_ms = durationMs;
  state.phase_deadline_at = durationMs !== null ? at + durationMs : null;
  state.paused_at = null;
  state.paused_remaining_ms = null;
  state.phase_active_ms = 0;
  state.pending_value = null;
  state.phase_seq += 1;
}

// ============================================================================
// Старт
// ============================================================================

export function start(plan: EnginePlan, at: number): [EngineState, Effect[]] {
  validatePlan(plan);
  const state: EngineState = {
    engine_version: ENGINE_VERSION,
    status: "active",
    phase: "PREP",
    cursor: { block_index: 0, set_index: 0, round_index: null },
    rest_kind: null,
    phase_started_at: at,
    phase_duration_ms: null,
    phase_deadline_at: null,
    paused_at: null,
    paused_remaining_ms: null,
    phase_seq: -1,
    active_elapsed_ms: 0,
    active_since: at,
    phase_active_ms: 0,
    pending_value: null,
    started_at: at,
    ended_at: null,
    last_at: at,
    block_started_at: null,
    logs: [],
  };
  const effects: Effect[] = [];
  enterBlock(plan, state, 0, at, effects);
  return [state, effects];
}

function enterBlock(plan: EnginePlan, state: EngineState, blockIndex: number, at: number, effects: Effect[]): void {
  state.block_started_at = at;
  effects.push({ type: "block_started", block_index: blockIndex, at });
  const prep = blockOf(plan, blockIndex).prep_seconds;
  const roundIndex = isIntervalBlock(plan, blockIndex) ? 0 : null;
  if (prep > 0) {
    enterPhase(state, "PREP", at, prep * 1000, blockIndex, 0, roundIndex);
  } else {
    enterWork(plan, state, blockIndex, 0, roundIndex, at);
  }
}

function enterWork(
  plan: EnginePlan, state: EngineState, blockIndex: number, setIndex: number, roundIndex: number | null, at: number,
): void {
  const block = blockOf(plan, blockIndex);
  let duration: number | null;
  if (block.kind === "interval") {
    duration = (block.interval as PlanInterval).work_seconds * 1000;
  } else {
    const spec = (block.sets as PlanSet[])[setIndex];
    duration = spec.kind === "time" ? (spec.target as number) * 1000 : null;
  }
  enterPhase(state, "WORK", at, duration, blockIndex, setIndex, roundIndex);
}

// ============================================================================
// Журнал подходов
// ============================================================================

function findLog(state: EngineState, blockIndex: unknown, setIndex: unknown, roundIndex: unknown): EngineLog | null {
  for (const log of state.logs) {
    if (log.block_index === blockIndex && log.set_index === setIndex && log.round_index === roundIndex) {
      return log;
    }
  }
  return null;
}

function appendLog(
  state: EngineState, effects: Effect[], blockIndex: number, setIndex: number, roundIndex: number | null,
  value: number | null, isExtra: boolean, at: number, effort: number | null = null, note: string | null = null,
): void {
  const log: EngineLog = {
    log_index: state.logs.length,
    block_index: blockIndex,
    set_index: setIndex,
    round_index: roundIndex,
    value,
    is_extra: isExtra,
    effort,
    note,
    logged_at: at,
  };
  state.logs.push(log);
  effects.push({ type: "set_logged", log: { ...log } });
}

const validValue = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= MAX_RESULT_VALUE;

const cleanEffort = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) && value >= 1 && value <= 5 ? value : null;

const cleanNote = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value.trim().slice(0, 1000) : null;

const opt = (payload: Payload, key: string): unknown => (payload[key] === undefined ? null : payload[key]);

// ============================================================================
// Следующий шаг
// ============================================================================

function afterSet(plan: EnginePlan, state: EngineState, at: number, effects: Effect[]): void {
  const { block_index: blockIndex, set_index: setIndex } = state.cursor;
  const sets = blockOf(plan, blockIndex).sets as PlanSet[];
  if (setIndex < sets.length - 1) {
    const rest = sets[setIndex].rest_after_seconds || 0;
    if (rest > 0) {
      enterPhase(state, "REST", at, rest * 1000, blockIndex, setIndex, null, "set");
    } else {
      enterWork(plan, state, blockIndex, setIndex + 1, null, at);
    }
    return;
  }
  afterBlock(plan, state, at, effects);
}

function afterRound(plan: EnginePlan, state: EngineState, at: number, effects: Effect[]): void {
  const blockIndex = state.cursor.block_index;
  const roundIndex = state.cursor.round_index as number;
  if (roundIndex < (blockOf(plan, blockIndex).interval as PlanInterval).rounds - 1) {
    enterWork(plan, state, blockIndex, roundIndex + 1, roundIndex + 1, at);
    return;
  }
  afterBlock(plan, state, at, effects);
}

function blockFinishedEffect(plan: EnginePlan, state: EngineState, blockIndex: number, at: number): Effect {
  const effect: Effect = { type: "block_finished", block_index: blockIndex, started_at: state.block_started_at, at };
  if (isIntervalBlock(plan, blockIndex)) {
    effect.completed_rounds = state.logs.filter((log) => log.block_index === blockIndex && !log.is_extra).length;
  }
  return effect;
}

function afterBlock(plan: EnginePlan, state: EngineState, at: number, effects: Effect[]): void {
  const blockIndex = state.cursor.block_index;
  effects.push(blockFinishedEffect(plan, state, blockIndex, at));
  if (blockIndex < plan.blocks.length - 1) {
    const rest = blockOf(plan, blockIndex).rest_after_block_seconds || 0;
    if (rest > 0) {
      const cursor = state.cursor;
      enterPhase(state, "REST", at, rest * 1000, blockIndex, cursor.set_index, cursor.round_index, "block");
    } else {
      enterBlock(plan, state, blockIndex + 1, at, effects);
    }
    return;
  }
  finish(state, at, effects, false);
}

function finish(state: EngineState, at: number, effects: Effect[], abandoned: boolean): void {
  accrue(state, at);
  state.phase = "COMPLETE";
  state.status = "completed";
  state.rest_kind = null;
  state.phase_started_at = at;
  state.phase_duration_ms = null;
  state.phase_deadline_at = null;
  state.paused_at = null;
  state.paused_remaining_ms = null;
  state.phase_active_ms = 0;
  state.pending_value = null;
  state.active_since = null;
  state.ended_at = at;
  state.phase_seq += 1;
  state.cursor = { ...state.cursor };
  effects.push({ type: "completed", abandoned, active_elapsed_ms: state.active_elapsed_ms });
}

function allPrescribedLogged(plan: EnginePlan, state: EngineState): boolean {
  for (let blockIndex = 0; blockIndex < plan.blocks.length; blockIndex += 1) {
    const logged = new Set(
      state.logs
        .filter((log) => log.block_index === blockIndex && !log.is_extra)
        .map((log) => `${log.set_index}:${log.round_index}`),
    );
    if (logged.size < prescribedCount(plan, blockIndex)) {
      return false;
    }
  }
  return true;
}

// ============================================================================
// Дедлайн
// ============================================================================

function onDeadline(plan: EnginePlan, state: EngineState, at: number, effects: Effect[]): void {
  const { phase, cursor } = state;
  const blockIndex = cursor.block_index;
  if (phase === "PREP") {
    enterWork(plan, state, blockIndex, cursor.set_index, cursor.round_index, at);
    return;
  }
  if (phase === "WORK") {
    if (isIntervalBlock(plan, blockIndex)) {
      const interval = blockOf(plan, blockIndex).interval as PlanInterval;
      const roundIndex = cursor.round_index as number;
      appendLog(state, effects, blockIndex, roundIndex, roundIndex, null, false, at);
      const restMs = interval.rest_seconds * 1000;
      if (interval.record_reps_per_round) {
        enterPhase(state, "RESULT", at, restMs, blockIndex, roundIndex, roundIndex);
        if (restMs === 0) {
          afterRound(plan, state, at, effects);
        }
      } else if (restMs > 0) {
        enterPhase(state, "REST", at, restMs, blockIndex, roundIndex, roundIndex, "round");
      } else {
        afterRound(plan, state, at, effects);
      }
      return;
    }
    const spec = setSpec(plan, blockIndex, cursor.set_index);
    appendLog(state, effects, blockIndex, cursor.set_index, null, spec.target, false, at);
    afterSet(plan, state, at, effects);
    return;
  }
  if (phase === "RESULT") {
    afterRound(plan, state, at, effects);
    return;
  }
  if (phase === "REST") {
    if (state.rest_kind === "set") {
      enterWork(plan, state, blockIndex, cursor.set_index + 1, null, at);
    } else if (state.rest_kind === "round") {
      afterRound(plan, state, at, effects);
    } else {
      enterBlock(plan, state, blockIndex + 1, at, effects);
    }
  }
}

// ============================================================================
// advance
// ============================================================================

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

const seqMatches = (state: EngineState, payload: Payload): boolean => opt(payload, "phase_seq") === state.phase_seq;

function resumeAt(state: EngineState, at: number): void {
  const remaining = state.paused_remaining_ms;
  state.paused_at = null;
  state.paused_remaining_ms = null;
  state.active_since = at;
  if (remaining !== null) {
    state.phase_deadline_at = at + remaining;
  }
}

function cancel(state: EngineState, at: number, effects: Effect[], reason: string): void {
  accrue(state, at);
  state.phase = "COMPLETE";
  state.status = "cancelled";
  state.rest_kind = null;
  state.phase_started_at = at;
  state.phase_duration_ms = null;
  state.phase_deadline_at = null;
  state.paused_at = null;
  state.paused_remaining_ms = null;
  state.phase_active_ms = 0;
  state.pending_value = null;
  state.active_since = null;
  state.ended_at = at;
  state.phase_seq += 1;
  effects.push({ type: "cancelled", reason });
}

const blockHasLogs = (state: EngineState, blockIndex: number): boolean =>
  state.logs.some((log) => log.block_index === blockIndex);

/** (state', effects). Чистая: вход не мутируется; невалидное/устаревшее событие — no-op. */
export function advance(plan: EnginePlan, state: EngineState, event: EngineEvent, atIn: number): [EngineState, Effect[]] {
  const kind = event.type;
  if (state.status !== "active" && kind !== "add_extra_set" && kind !== "correct_previous") {
    return [state, []];
  }
  const at = Math.max(Math.trunc(atIn), state.last_at);
  const payload: Payload = event.payload ?? {};
  const next = clone(state);
  const effects: Effect[] = [];

  if (kind === "deadline") {
    const deadline = next.phase_deadline_at;
    if (next.paused_at !== null || deadline === null || at < deadline) {
      return [state, []];
    }
    accrue(next, deadline);
    onDeadline(plan, next, deadline, effects);
    return [next, effects];
  }

  if (kind === "skip_wait") {
    if (!seqMatches(next, payload) || !["PREP", "REST", "RESULT"].includes(next.phase)) {
      return [state, []];
    }
    if (next.phase === "RESULT" && next.phase_deadline_at === null && next.paused_remaining_ms === null) {
      return [state, []];
    }
    if (next.paused_at !== null) {
      resumeAt(next, at);
    }
    accrue(next, at);
    onDeadline(plan, next, at, effects);
    return [next, effects];
  }

  if (kind === "pause") {
    if (!seqMatches(next, payload) || next.paused_at !== null || next.phase === "COMPLETE") {
      return [state, []];
    }
    accrue(next, at);
    next.active_since = null;
    next.paused_at = at;
    if (next.phase_deadline_at !== null) {
      next.paused_remaining_ms = Math.max(0, next.phase_deadline_at - at);
      next.phase_deadline_at = null;
    }
    return [next, effects];
  }

  if (kind === "resume") {
    if (!seqMatches(next, payload) || next.paused_at === null) {
      return [state, []];
    }
    resumeAt(next, at);
    next.last_at = Math.max(next.last_at, at);
    return [next, effects];
  }

  if (kind === "stop") {
    if (!seqMatches(next, payload) || next.phase !== "WORK") {
      return [state, []];
    }
    const cursor = next.cursor;
    if (isIntervalBlock(plan, cursor.block_index)) {
      return [state, []];
    }
    const spec = setSpec(plan, cursor.block_index, cursor.set_index);
    if (spec.kind !== "time" && spec.kind !== "max_time") {
      return [state, []];
    }
    if (next.paused_at !== null) {
      resumeAt(next, at);
    }
    accrue(next, at);
    const measured = msToSeconds(next.phase_active_ms);
    if (spec.kind === "time") {
      appendLog(next, effects, cursor.block_index, cursor.set_index, null, measured, false, at);
      afterSet(plan, next, at, effects);
      return [next, effects];
    }
    enterPhase(next, "RESULT", at, null, cursor.block_index, cursor.set_index, null);
    next.pending_value = measured;
    return [next, effects];
  }

  if (kind === "submit_result") {
    return submitResult(plan, state, next, payload, at);
  }

  if (kind === "finish_early") {
    if (!next.logs.some((log) => !log.is_extra)) {
      cancel(next, at, effects, "zero_work");
      return [next, effects];
    }
    accrue(next, at);
    const cursor = next.cursor;
    const blockAlreadyFinished = next.phase === "REST" && next.rest_kind === "block";
    const blockBegan = next.phase !== "PREP" || blockHasLogs(next, cursor.block_index);
    if (!blockAlreadyFinished && blockBegan) {
      effects.push(blockFinishedEffect(plan, next, cursor.block_index, at));
    }
    finish(next, at, effects, !allPrescribedLogged(plan, next));
    return [next, effects];
  }

  if (kind === "cancel") {
    cancel(next, at, effects, "cancel");
    return [next, effects];
  }

  if (kind === "add_extra_set") {
    return addExtraSet(plan, state, next, payload, at);
  }

  if (kind === "correct_previous") {
    return correctPrevious(state, next, payload, at);
  }

  return [state, []];
}

function submitResult(
  plan: EnginePlan, state: EngineState, next: EngineState, payload: Payload, at: number,
): [EngineState, Effect[]] {
  const cursor = next.cursor;
  const value = payload.value;
  if (!validValue(value)) {
    return [state, []];
  }
  if (opt(payload, "block_index") !== cursor.block_index || opt(payload, "set_index") !== cursor.set_index) {
    return [state, []];
  }
  if (opt(payload, "round_index") !== cursor.round_index) {
    return [state, []];
  }
  const effort = cleanEffort(payload.effort);
  const note = cleanNote(payload.note);
  const blockIndex = cursor.block_index;
  if (isIntervalBlock(plan, blockIndex)) {
    if (next.phase !== "RESULT") {
      return [state, []];
    }
    const log = findLog(next, blockIndex, cursor.set_index, cursor.round_index);
    if (log === null) {
      return [state, []];
    }
    log.value = value;
    log.effort = effort;
    log.note = note;
    const effects: Effect[] = [{ type: "set_corrected", log: { ...log } }];
    const deadline = next.phase_deadline_at;
    const remaining = next.paused_remaining_ms;
    next.phase = "REST";
    next.rest_kind = "round";
    next.phase_seq += 1;
    next.phase_deadline_at = deadline;
    next.paused_remaining_ms = remaining;
    return [next, effects];
  }
  if (next.phase === "PREP") {
    if (next.paused_at !== null) {
      resumeAt(next, at);
    }
    accrue(next, at);
    enterWork(plan, next, blockIndex, cursor.set_index, null, at);
  }
  if (next.phase !== "WORK" && next.phase !== "RESULT") {
    return [state, []];
  }
  if (next.paused_at !== null) {
    resumeAt(next, at);
  }
  accrue(next, at);
  const effects: Effect[] = [];
  appendLog(next, effects, blockIndex, cursor.set_index, null, value, false, at, effort, note);
  afterSet(plan, next, at, effects);
  return [next, effects];
}

function addExtraSet(
  plan: EnginePlan, state: EngineState, next: EngineState, payload: Payload, at: number,
): [EngineState, Effect[]] {
  if (next.status === "cancelled") {
    return [state, []];
  }
  const blockIndex = payload.block_index;
  const value = payload.value;
  if (!isInt(blockIndex) || blockIndex < 0 || blockIndex >= plan.blocks.length) {
    return [state, []];
  }
  const block = blockOf(plan, blockIndex);
  if (block.kind !== "sets" || !(block.extra_sets_allowed ?? true) || !validValue(value)) {
    return [state, []];
  }
  const sets = block.sets as PlanSet[];
  const logged = new Set(
    next.logs.filter((log) => log.block_index === blockIndex && !log.is_extra).map((log) => log.set_index),
  );
  if (logged.size < sets.length) {
    return [state, []];
  }
  const extras = next.logs.filter((log) => log.block_index === blockIndex && log.is_extra).length;
  next.last_at = Math.max(next.last_at, at);
  if (next.active_since !== null) {
    accrue(next, at);
  }
  const effects: Effect[] = [];
  appendLog(
    next, effects, blockIndex, sets.length + extras, null, value, true, at, cleanEffort(payload.effort),
    cleanNote(payload.note),
  );
  return [next, effects];
}

function correctPrevious(state: EngineState, next: EngineState, payload: Payload, at: number): [EngineState, Effect[]] {
  if (next.status === "cancelled") {
    return [state, []];
  }
  const value = payload.value;
  if (!validValue(value)) {
    return [state, []];
  }
  const log = findLog(next, opt(payload, "block_index"), opt(payload, "set_index"), opt(payload, "round_index"));
  if (log === null) {
    return [state, []];
  }
  const effort = "effort" in payload ? cleanEffort(payload.effort) : log.effort;
  const note = "note" in payload ? cleanNote(payload.note) : log.note;
  if (log.value === value && log.effort === effort && log.note === note) {
    return [state, []];
  }
  log.value = value;
  log.effort = effort;
  log.note = note;
  next.last_at = Math.max(next.last_at, at);
  if (next.active_since !== null) {
    accrue(next, at);
  }
  return [next, [{ type: "set_corrected", log: { ...log } }]];
}

// ============================================================================
// Проекция и перестроение
// ============================================================================

export function project(plan: EnginePlan, stateIn: EngineState, now: number): [EngineState, Effect[], Effect[]] {
  let state = stateIn;
  const events: Effect[] = [];
  const effects: Effect[] = [];
  let guard = 0;
  while (
    state.status === "active" && state.paused_at === null && state.phase_deadline_at !== null
    && state.phase_deadline_at <= now
  ) {
    const deadline = state.phase_deadline_at;
    const [nextState, stepEffects] = advance(plan, state, { type: "deadline" }, deadline);
    state = nextState;
    events.push({ type: "deadline", at: deadline });
    effects.push(...stepEffects);
    guard += 1;
    if (guard > 10_000) {
      throw new EngineError("projection did not converge");
    }
  }
  return [state, events, effects];
}

export function applyEvent(
  plan: EnginePlan, state: EngineState, event: EngineEvent, at: number,
): [EngineState, Effect[], Effect[]] {
  const [projected, deadlineEvents, effects] = project(plan, state, at);
  const [next, eventEffects] = advance(plan, projected, event, at);
  return [next, deadlineEvents, [...effects, ...eventEffects]];
}

export function rebuild(plan: EnginePlan, events: { type: string; at: number; payload?: Payload }[]): EngineState {
  if (events.length === 0 || events[0].type !== "start") {
    throw new EngineError("first event must be start");
  }
  let [state] = start(plan, events[0].at);
  for (const event of events.slice(1)) {
    [state] = advance(plan, state, event, event.at);
  }
  return state;
}

// ============================================================================
// Аудио-хуки (§6)
// ============================================================================

function phaseCues(state: EngineState): TimelineCue[] {
  const cues: TimelineCue[] = [];
  const { phase } = state;
  const deadline = state.phase_deadline_at;
  if (phase === "WORK") {
    cues.push({ type: "work_start", at: state.phase_started_at });
  }
  if (phase === "COMPLETE" && state.status === "completed") {
    cues.push({ type: "workout_complete", at: state.phase_started_at });
  }
  if (deadline === null) {
    return cues;
  }
  const duration = state.phase_duration_ms || 0;
  if ((phase === "PREP" || phase === "REST") && duration >= WARN_10S_MIN_PHASE_MS) {
    cues.push({ type: "warn_10s", at: deadline - 10_000 });
  }
  if (phase === "PREP" || phase === "REST" || phase === "WORK") {
    for (const n of [3, 2, 1]) {
      if (duration >= n * 1000) {
        cues.push({ type: `count_${n}`, at: deadline - n * 1000 });
      }
    }
  }
  if (phase === "WORK") {
    cues.push({ type: "work_end", at: deadline });
  }
  if (phase === "REST") {
    cues.push({ type: "rest_end", at: deadline });
  }
  return cues;
}

const CUE_ORDER: Record<string, number> = { rest_end: 0, work_end: 0, work_start: 1, workout_complete: 2 };

export function timeline(plan: EnginePlan, state: EngineState): TimelineCue[] {
  if (state.status === "cancelled" || state.paused_at !== null) {
    return [];
  }
  const cues = phaseCues(state);
  if (state.status === "active" && state.phase_deadline_at !== null) {
    const [nextState] = advance(plan, state, { type: "deadline" }, state.phase_deadline_at);
    if (nextState.phase_seq !== state.phase_seq) {
      cues.push(...phaseCues(nextState));
    }
  }
  const unique = new Map<string, TimelineCue>();
  for (const cue of cues) {
    unique.set(`${cue.type}@${cue.at}`, cue);
  }
  return [...unique.values()].sort((a, b) => {
    if (a.at !== b.at) {
      return a.at - b.at;
    }
    const orderDiff = (CUE_ORDER[a.type] ?? 0) - (CUE_ORDER[b.type] ?? 0);
    if (orderDiff !== 0) {
      return orderDiff;
    }
    return a.type < b.type ? -1 : a.type > b.type ? 1 : 0;
  });
}

// ============================================================================
// Отображение (клиент — проекция серверного состояния, C1/C2)
// ============================================================================

/** Остаток текущей фазы в мс от единственного дедлайна; на паузе — замороженный остаток; null — фаза
 * ждёт пользователя. nowServerMs = Date.now() + serverOffset. */
export function remainingMs(state: EngineState, nowServerMs: number): number | null {
  if (state.paused_at !== null) {
    return state.paused_remaining_ms;
  }
  if (state.phase_deadline_at === null) {
    return null;
  }
  return Math.max(0, state.phase_deadline_at - nowServerMs);
}

/** Активное время тренировки к моменту nowServerMs (паузы исключены). */
export function activeElapsedMs(state: EngineState, nowServerMs: number): number {
  return state.active_elapsed_ms + (state.active_since !== null ? Math.max(0, nowServerMs - state.active_since) : 0);
}
