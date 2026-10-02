/**
 * Клиент для /api/v2/* (issue #167, волна 4) — отдельный от api.ts файл, тот
 * же принцип, что развёл app/web/schemas_v2.py от app/web/schemas.py на
 * бэкенде: v2-схема данных (TrainingPlan/ProgramInclusion/TrainingSession)
 * принципиально другая, не расширение старой. Единственный файл фронтенда
 * (вместе с DashboardScreen.tsx), которому разрешено упоминать /api/v2 — см.
 * allowlist в tests/test_web/test_v2_not_wired_to_ui.py.
 */

import type { SessionCreatePayload } from "./journalLog";

/**
 * Извлекает human-readable сообщение ошибки из FastAPI response (issue #212).
 * FastAPI возвращает `{"detail": "message"}` — берём detail, если это строка.
 * Для 422 (Pydantic validation) detail — массив объектов, не строка — fallback.
 */
async function extractErrorMessage(
  method: string,
  path: string,
  response: Response,
): Promise<string> {
  const fallback = `${method} ${path} failed: ${response.status}`;
  try {
    const data = await response.json();
    if (data && typeof data.detail === "string") {
      return data.detail;
    }
  } catch {
    // JSON parsing failed or response already consumed — use fallback
  }
  return fallback;
}

export interface DashboardEquipmentResponse {
  type: string;
  value: string | null;
  item_id: number | null;
  label: string;
  needs_new_equipment: boolean;
}

export interface DashboardBlockResponse {
  target: number;
  work_sets: number;
  equipment: DashboardEquipmentResponse;
}

/**
 * GET /api/v2/dashboard/status. status="ready" — единственный случай, когда
 * block_a/block_b заполнены; остальные статусы — то же, что читает
 * DashboardScreen.tsx::STATUS_MESSAGES.
 *
 * Тест на максимум блока A и чередование тяжёлой блока Б старой схемы
 * (issue #89/#97) сознательно не перенесены в этой волне — в
 * progression_state v2 нет ни якорной даты теста, ни расчёта чётности (см.
 * app/web/schemas_v2_dashboard.py). block_a/block_b здесь всегда "обычная"
 * форма тренировки.
 */
export interface DashboardStatusResponse {
  status: "not_migrated" | "too_early" | "gap_retest_required" | "multiple_active_inclusions" | "ready";
  program_name: string | null;
  is_gap_rollback: boolean;
  work_sets_growth_reason: "stall" | "ceiling" | null;
  block_a: DashboardBlockResponse | null;
  block_b: DashboardBlockResponse | null;
}

async function apiV2Get<T>(path: string, initDataRaw: string): Promise<T> {
  const response = await fetch(path, {
    headers: { "X-Telegram-Init-Data": initDataRaw },
  });
  if (!response.ok) {
    const message = await extractErrorMessage("GET", path, response);
    throw new Error(message);
  }
  return (await response.json()) as T;
}

async function apiV2Post<TBody, TResult>(path: string, initDataRaw: string, body: TBody): Promise<TResult> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "X-Telegram-Init-Data": initDataRaw, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const message = await extractErrorMessage("POST", path, response);
    throw new Error(message);
  }
  return (await response.json()) as TResult;
}

async function apiV2Patch<TBody, TResult>(path: string, initDataRaw: string, body: TBody): Promise<TResult> {
  const response = await fetch(path, {
    method: "PATCH",
    headers: { "X-Telegram-Init-Data": initDataRaw, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const message = await extractErrorMessage("PATCH", path, response);
    throw new Error(message);
  }
  return (await response.json()) as TResult;
}

async function apiV2Put(path: string, initDataRaw: string): Promise<void> {
  const response = await fetch(path, {
    method: "PUT",
    headers: { "X-Telegram-Init-Data": initDataRaw },
  });
  if (!response.ok) {
    const message = await extractErrorMessage("PUT", path, response);
    throw new Error(message);
  }
}

async function apiV2Delete(path: string, initDataRaw: string): Promise<void> {
  const response = await fetch(path, {
    method: "DELETE",
    headers: { "X-Telegram-Init-Data": initDataRaw },
  });
  if (!response.ok) {
    const message = await extractErrorMessage("DELETE", path, response);
    throw new Error(message);
  }
}

export async function fetchDashboardStatus(initDataRaw: string): Promise<DashboardStatusResponse> {
  return apiV2Get<DashboardStatusResponse>("/api/v2/dashboard/status", initDataRaw);
}

// --- GET /api/v2/exercises (Checkpoint 3A, issue #196) — Exercise Library без UI ----

export interface ExerciseResponseV2 {
  id: number;
  name: string;
  metric_type: string;
  category: string;
  subcategory: string | null;
}

export async function fetchExercises(initDataRaw: string): Promise<ExerciseResponseV2[]> {
  const response = await apiV2Get<{ exercises: ExerciseResponseV2[] }>("/api/v2/exercises", initDataRaw);
  return response.exercises;
}

// --- Workout (Phase C2/C4a, issue #188) — «Мои тренировки» ------------------------

/** items опционально — заполняется только detail-эндпоинтом (GET
 * /workouts/{id}), list/create/patch его не возвращают (см. backend
 * app/web/routes_v2.py::_workout_response). */
export interface WorkoutItemResponseV2 {
  id: number;
  exercise_id: number;
  exercise_name: string;
  order_index: number;
  protocol: Record<string, unknown>;
}

export interface WorkoutResponseV2 {
  id: number;
  title: string;
  source_type: string;
  owner_user_id: number | null;
  items: WorkoutItemResponseV2[] | null;
}

export async function listWorkouts(initDataRaw: string): Promise<WorkoutResponseV2[]> {
  const response = await apiV2Get<{ workouts: WorkoutResponseV2[] }>("/api/v2/workouts", initDataRaw);
  return response.workouts;
}

/** История одной тренировки (Workout Detail): завершённые сессии пользователя,
 * чей замороженный снимок ссылается на этот Workout; новые первыми. */
export interface WorkoutSessionSummaryV2 {
  id: number;
  performed_at: string;
  exercises_count: number;
  sets_done: number;
}

export type FavoriteTargetType = "workout" | "program";

export interface FavoriteV2 {
  target_type: FavoriteTargetType;
  target_id: number;
  title: string;
  subtitle: string | null;
}

export async function listFavorites(initDataRaw: string): Promise<FavoriteV2[]> {
  const response = await apiV2Get<{ favorites: FavoriteV2[] }>("/api/v2/favorites", initDataRaw);
  return response.favorites;
}

/** Идемпотентно: PUT ставит, DELETE снимает (issue #272). */
export async function setFavorite(
  initDataRaw: string, targetType: FavoriteTargetType, targetId: number, favorite: boolean,
): Promise<void> {
  const path = `/api/v2/favorites/${targetType}/${targetId}`;
  return favorite ? apiV2Put(path, initDataRaw) : apiV2Delete(path, initDataRaw);
}

export async function listWorkoutSessions(initDataRaw: string, workoutId: number): Promise<WorkoutSessionSummaryV2[]> {
  const response = await apiV2Get<{ sessions: WorkoutSessionSummaryV2[] }>(
    `/api/v2/workouts/${workoutId}/sessions`, initDataRaw,
  );
  return response.sessions;
}

export async function createWorkout(initDataRaw: string, title: string): Promise<WorkoutResponseV2> {
  return apiV2Post<{ title: string }, WorkoutResponseV2>("/api/v2/workouts", initDataRaw, { title });
}

export async function getWorkout(initDataRaw: string, workoutId: number): Promise<WorkoutResponseV2> {
  return apiV2Get<WorkoutResponseV2>(`/api/v2/workouts/${workoutId}`, initDataRaw);
}

export async function updateWorkout(initDataRaw: string, workoutId: number, title: string): Promise<WorkoutResponseV2> {
  return apiV2Patch<{ title: string }, WorkoutResponseV2>(`/api/v2/workouts/${workoutId}`, initDataRaw, { title });
}

/** Phase C4b-1 (issue #188) — под уже существующий C1 POST /exercises
 * (backend готов с C1, frontend не был подключён — теперь Exercise
 * Picker его использует для "Создать своё упражнение"). */
export async function createExercise(initDataRaw: string, name: string): Promise<ExerciseResponseV2> {
  return apiV2Post<{ name: string }, ExerciseResponseV2>("/api/v2/exercises", initDataRaw, { name });
}

/** Мягкое удаление своей тренировки (issue #261): история в Журнале остаётся. */
export async function deleteWorkout(initDataRaw: string, workoutId: number): Promise<void> {
  return apiV2Delete(`/api/v2/workouts/${workoutId}`, initDataRaw);
}

/** Копия «<название> (копия)» с тем же составом и протоколами (issue #261). */
export async function duplicateWorkout(initDataRaw: string, workoutId: number): Promise<WorkoutResponseV2> {
  return apiV2Post<Record<string, never>, WorkoutResponseV2>(
    `/api/v2/workouts/${workoutId}/duplicate`, initDataRaw, {},
  );
}

export async function addWorkoutItem(
  initDataRaw: string, workoutId: number, exerciseId: number, protocol: Record<string, unknown>,
): Promise<WorkoutItemResponseV2> {
  return apiV2Post<{ exercise_id: number; protocol: Record<string, unknown> }, WorkoutItemResponseV2>(
    `/api/v2/workouts/${workoutId}/items`, initDataRaw, { exercise_id: exerciseId, protocol },
  );
}

export async function updateWorkoutItem(
  initDataRaw: string, workoutId: number, itemId: number,
  changes: { exerciseId?: number; protocol?: Record<string, unknown> },
): Promise<WorkoutItemResponseV2> {
  const body: { exercise_id?: number; protocol?: Record<string, unknown> } = {};
  if (changes.exerciseId !== undefined) {
    body.exercise_id = changes.exerciseId;
  }
  if (changes.protocol !== undefined) {
    body.protocol = changes.protocol;
  }
  return apiV2Patch<typeof body, WorkoutItemResponseV2>(
    `/api/v2/workouts/${workoutId}/items/${itemId}`, initDataRaw, body,
  );
}

export async function deleteWorkoutItem(initDataRaw: string, workoutId: number, itemId: number): Promise<void> {
  return apiV2Delete(`/api/v2/workouts/${workoutId}/items/${itemId}`, initDataRaw);
}

export async function moveWorkoutItem(
  initDataRaw: string, workoutId: number, itemId: number, direction: "up" | "down",
): Promise<WorkoutResponseV2> {
  return apiV2Post<{ direction: "up" | "down" }, WorkoutResponseV2>(
    `/api/v2/workouts/${workoutId}/items/${itemId}/move`, initDataRaw, { direction },
  );
}

/**
 * Волна 5 (issue #185, экран сессии) — те же файлы остаются единственными,
 * которым разрешено упоминать /api/v2 (allowlist в
 * tests/test_web/test_v2_not_wired_to_ui.py); новые экраны сессии
 * (SessionPreScreen/SessionLiveScreen/SessionSummaryScreen/...) импортируют
 * только эти функции/типы, не строку пути напрямую.
 */

// --- GET /api/v2/plan — нужен, чтобы найти plan_item_id блоков A/Б по роли
// (snapshot.exercises) перед стартом живой сессии, см. SessionPreScreen.tsx. ---

export interface ProgramInclusionResponseV2 {
  id: number;
  program_id: number;
  program_name: string;
  is_active: boolean;
  started_at: string;
  expires_at: string | null;
  snapshot: { exercises?: { role: string; exercise_id: number; name: string; metric_type: string }[] } & Record<
    string, unknown
  >;
  progression_state: Record<string, unknown>;
  /** issue #266 — только для курса с явно заданной длиной. */
  duration_weeks?: number | null;
  current_week?: number | null;
}

export interface PlanItemResponseV2 {
  id: number;
  exercise_id: number;
  complex_id: number | null;
  count_per_week: number;
  day_of_week: number | null;
  week_phase: string | null;
  program_inclusion_id: number | null;
  plan_week_id: number | null;
  /** Phase B2 gate fix (issue #215) — Workout title (Complex.name), не
   * Exercise.name — только для complex-based PlanItem. */
  complex_name: string | null;
  /** Phase D2/D3 (issue #188) — "user"|"system"|null (нет complex_id
   * вовсе). Решает, показывать ли "Редактировать тренировку" на
   * карточке (только для user Workout). owner_user_id намеренно не
   * отдаётся backend'ом. */
  complex_source_type: "user" | "system" | null;
  /** issue #258 — выполнений на своей неделе (завершённые сессии). */
  done_count: number;
}

/**
 * issue #193 (WORKER B) — реальная PlanWeek (Checkpoint 1/1.1, issue #188),
 * не то же самое, что PlanItemResponseV2.week_phase (свойство самой строки
 * плана, унаследованное от ProgramItem, не привязка к конкретной
 * календарной неделе). "Планы" группирует plan_items по plan_week_id,
 * ссылающемуся на id из этого списка, а не по week_phase.
 */
export interface PlanWeekResponseV2 {
  id: number;
  week_number: number;
  start_date: string;
  phase: string;
}

export interface TrainingPlanResponseV2 {
  id: number;
  created_at: string;
  program_inclusions: ProgramInclusionResponseV2[];
  plan_items: PlanItemResponseV2[];
  plan_weeks: PlanWeekResponseV2[];
}

export async function fetchPlan(initDataRaw: string): Promise<TrainingPlanResponseV2 | null> {
  const response = await apiV2Get<{ plan: TrainingPlanResponseV2 | null }>("/api/v2/plan", initDataRaw);
  return response.plan;
}

// --- Живая сессия: POST /sessions/live, /phase/next, /sets:batch, /complete,
// GET /sessions/live/active (app/web/schemas_v2_session.py) ------------------

export interface LiveSessionPhaseResponse {
  name: "get_ready" | "go" | "rest" | "done";
  ends_at: string | null;
}

export interface SetLogResponseV2 {
  set_number: number;
  is_max_set: boolean;
  metric_type: string;
  value: string;
  unit: string;
  effort: string | null;
  note: string | null;
  is_extra?: boolean;
}

export interface LiveSetTargetResponse {
  set_number: number;
  metric_type: string;
  value: string;
  unit: string;
}

export interface LiveSessionBlockResponse {
  order_index: number;
  exercise_id: number | null;
  complex_id: number | null;
  targets: LiveSetTargetResponse[];
  set_logs: SetLogResponseV2[];
  /** Phase B2 gate fix (issue #215) — SessionBlock.result (Phase B1),
   * контракт для interval: {type: "interval", started_at, completed_at,
   * planned_duration_seconds, actual_duration_seconds, completed_cycles}.
   * null для standard STANDARD/REPS/MAX блоков. */
  result: Record<string, unknown> | null;
  /** R1 — идентичность блока из ЗАМОРОЖЕННОГО снимка тренировки (не из
   * изменяемого Workout). null у legacy/STEP-блоков без снимка. */
  protocol_type: ProtocolType | null;
  exercise_name: string | null;
  rest_seconds: number | null;
  /** Эффективное время начала блока; null — блок ещё не начат. */
  started_at: string | null;
  interval_config: IntervalConfigResponse | null;
}

export type ProtocolType = "reps_sets" | "time_sets" | "max_effort" | "interval";

export interface IntervalConfigResponse {
  total_duration_seconds: number;
  work_seconds: number;
  rest_seconds: number;
}

export interface BlockProgressionResponseV2 {
  target_before: number;
  target_after: number;
  equipment_changed: boolean;
}

export interface SessionProgressionResponseV2 {
  block_a: BlockProgressionResponseV2;
  block_b: BlockProgressionResponseV2;
}

/** Phase B1 (issue #215) — server-authoritative interval timing state,
 * вычисляется бэкендом на лету из performed_at+protocol, не персистится.
 * Только для interval workouts, null для standard STEP/manual path. */
export interface IntervalStateResponse {
  execution_started_at: string;
  total_end_at: string;
  phase: "get_ready" | "work" | "rest" | "done";
  phase_ends_at: string | null;
  total_duration_seconds: number;
  work_seconds: number;
  rest_seconds: number;
  completed_cycles: number;
}

export interface LiveSessionResponse {
  id: number;
  client_session_id: string;
  status: "started" | "completed";
  phase: LiveSessionPhaseResponse;
  phase_index: number;
  current_block_index: number;
  current_set_number: number;
  blocks: LiveSessionBlockResponse[];
  /** Phase B1 (issue #215) — момент генерации ответа на сервере, НЕ
   * persisted значение. Клиент вычисляет clockOffsetMs = parse(server_time)
   * - Date.now() один раз на каждый ответ, дальше использует
   * Date.now() + clockOffsetMs как скорректированное "сейчас" — не
   * сравнивает абсолютные серверные timestamps с голым Date.now(). */
  server_time: string;
  interval: IntervalStateResponse | null;
  /** R1 — сессия стоит перед ещё не начатым блоком: показывается
   * interstitial "Следующее упражнение … Начать", блок сам не стартует. */
  awaiting_block_start: boolean;
  /** Phase B2 gate fix (issue #215) — резолвится бэкендом (тот же путь,
   * что Журнал уже использует), нужен для reload/recovery: без него
   * PlanSessionFlow/IntervalLiveScreen получали пустой title после
   * перезагрузки посреди тренировки. */
  title: string | null;
}

export interface LiveSessionCompleteResponse extends LiveSessionResponse {
  progression_result: SessionProgressionResponseV2 | null;
  progression_skipped_reason: string | null;
}

export interface LiveSetBatchEntry {
  set_index: number;
  exercise_id: number;
  value: string;
  effort?: string | null;
  note?: string | null;
  /** R1 — блок, для которого записан подход (одно упражнение может
   * встречаться в тренировке несколько раз). */
  block_index?: number | null;
  /** #264 — подход сверх плана («+ Ещё подход»). */
  is_extra?: boolean;
}

export async function startLiveSession(
  initDataRaw: string,
  clientSessionId: string,
  planItemIds: number[],
): Promise<LiveSessionResponse> {
  return apiV2Post("/api/v2/sessions/live", initDataRaw, {
    client_session_id: clientSessionId,
    plan_item_ids: planItemIds,
  });
}

export async function fetchActiveLiveSession(initDataRaw: string): Promise<LiveSessionResponse | null> {
  const response = await apiV2Get<{ session: LiveSessionResponse | null }>(
    "/api/v2/sessions/live/active", initDataRaw,
  );
  return response.session;
}

export async function advanceLiveSessionPhase(
  initDataRaw: string,
  sessionId: number,
  expectedPhaseIndex: number,
): Promise<LiveSessionResponse> {
  return apiV2Post(`/api/v2/sessions/live/${sessionId}/phase/next`, initDataRaw, {
    expected_phase_index: expectedPhaseIndex,
  });
}

export async function batchLiveSessionSets(
  initDataRaw: string,
  sessionId: number,
  sets: LiveSetBatchEntry[],
): Promise<LiveSessionResponse> {
  return apiV2Post(`/api/v2/sessions/live/${sessionId}/sets:batch`, initDataRaw, { sets });
}

export async function startLiveBlock(
  initDataRaw: string,
  sessionId: number,
  expectedBlockIndex: number,
): Promise<LiveSessionResponse> {
  return apiV2Post(`/api/v2/sessions/live/${sessionId}/blocks/start`, initDataRaw, {
    expected_block_index: expectedBlockIndex,
  });
}

/** Дедлайн interval-блока: середина тренировки — сессия остаётся "started"
 * и ждёт следующий блок; последний блок — статус "completed". */
export async function finishLiveIntervalBlock(
  initDataRaw: string,
  sessionId: number,
  expectedBlockIndex: number,
): Promise<LiveSessionCompleteResponse> {
  return apiV2Post(`/api/v2/sessions/live/${sessionId}/blocks/finish`, initDataRaw, {
    expected_block_index: expectedBlockIndex,
  });
}

export async function completeLiveSession(
  initDataRaw: string,
  sessionId: number,
  abandoned: boolean,
  review?: { effort?: string | null; comment?: string | null },
): Promise<LiveSessionCompleteResponse> {
  // effort/comment — оценка тренировки целиком (необязательно); пустое не шлём.
  return apiV2Post(`/api/v2/sessions/live/${sessionId}/complete`, initDataRaw, {
    abandoned,
    ...(review?.effort ? { effort: review.effort } : {}),
    ...(review?.comment ? { comment: review.comment } : {}),
  });
}

// --- Каскад прогрессии (правка исторической сессии, раздел 10.6/15) --------

export interface SetLogInputV2 {
  set_number: number;
  metric_type: "reps" | "time" | "weight" | "angle" | "distance";
  value: string;
  unit: string;
  is_max_set?: boolean;
  effort?: string | null;
  note?: string | null;
}

export interface PlanItemDeltaResponse {
  plan_item_id: number | null;
  exercise: string;
  before: number;
  after: number;
}

export interface ProgressionPreviewResponse {
  deltas: PlanItemDeltaResponse[];
}

export async function previewProgressionCascade(
  initDataRaw: string,
  inclusionId: number,
  editedSessionId: number,
  blockA?: SetLogInputV2[],
  blockB?: SetLogInputV2[],
): Promise<ProgressionPreviewResponse> {
  return apiV2Post(`/api/v2/program-inclusions/${inclusionId}/progression/preview`, initDataRaw, {
    edited_session_id: editedSessionId, block_a: blockA ?? null, block_b: blockB ?? null,
  });
}

export async function applyProgressionCascade(
  initDataRaw: string,
  inclusionId: number,
  editedSessionId: number,
  blockA?: SetLogInputV2[],
  blockB?: SetLogInputV2[],
): Promise<ProgressionPreviewResponse> {
  return apiV2Post(`/api/v2/program-inclusions/${inclusionId}/progression/apply`, initDataRaw, {
    edited_session_id: editedSessionId, block_a: blockA ?? null, block_b: blockB ?? null,
  });
}

// --- Журнал сессий (GET /api/v2/sessions) — источник "вчерашней сессии" для
// правки/preview выше. ---------------------------------------------------

export interface SessionResponseV2 {
  id: number;
  source: string;
  status: string;
  performed_at: string;
  effort: string | null;
  comment: string | null;
  /** Checkpoint 4C (issue #188) — резолвится на бэкенде через
   * SessionPlanItem, не пересчитывается на фронте. null — сессия без связи
   * (легаси POST /sessions в обход live-flow, или до Checkpoint 4A). */
  title: string | null;
  blocks: SessionBlockResponseV2[];
  /** #263 — свободная активность (source=freeform): тип и длительность; иначе null. */
  activity_type?: string | null;
  duration_seconds?: number | null;
  /** R2 — серверное решение "можно ли безопасно удалить"; фронт показывает
   * "Удалить" только при true и не строит своих эвристик. */
  can_delete: boolean;
  /** #262 — тот же серверный предикат: «Изменить»/«Повторить» только при true. */
  can_edit: boolean;
  progression_result: SessionProgressionResponseV2 | null;
  progression_skipped_reason: string | null;
}

export interface SessionSetTargetResponseV2 {
  set_number: number;
  is_max_set: boolean;
  metric_type: string;
  value: string;
  unit: string;
}

/** R2 — блок сессии для Журнала: каждый блок рендерится независимо, его
 * протокол (protocol_type) берётся из замороженного снимка по позиции. */
export interface SessionBlockResponseV2 {
  order_index: number;
  exercise_id: number | null;
  complex_id: number | null;
  set_logs: SetLogResponseV2[];
  /** Phase B2 gate fix (issue #215) — interval result для Журнала. */
  result: Record<string, unknown> | null;
  protocol_type: ProtocolType | null;
  /** null — человекочитаемого имени нет (внутренняя STEP-роль). */
  exercise_name: string | null;
  started_at: string | null;
  set_targets: SessionSetTargetResponseV2[];
  interval_config: IntervalConfigResponse | null;
}

export async function fetchSessions(
  initDataRaw: string, limit = 20, status?: "started" | "completed",
): Promise<SessionResponseV2[]> {
  const statusParam = status ? `&status=${status}` : "";
  const response = await apiV2Get<{ sessions: SessionResponseV2[] }>(
    `/api/v2/sessions?limit=${limit}${statusParam}`, initDataRaw,
  );
  return response.sessions;
}

export interface SessionsPage {
  sessions: SessionResponseV2[];
  has_more: boolean;
}

/** Страница Журнала v2 — тот же GET /sessions (limit/offset), has_more
 * считает сервер. */
export async function fetchSessionsPage(
  initDataRaw: string, limit: number, offset: number, status: "started" | "completed",
  range?: { from: string; to: string },
): Promise<SessionsPage> {
  const dates = range ? `&date_from=${range.from}&date_to=${range.to}` : "";
  return apiV2Get<SessionsPage>(
    `/api/v2/sessions?limit=${limit}&offset=${offset}&status=${status}${dates}`, initDataRaw,
  );
}

/** GET /journal/days (#256) — дни месяца с завершёнными тренировками. */
export interface JournalDaysResponse {
  month: string;
  timezone: string;
  days: { date: string; count: number }[];
  latest_month: string | null;
}

export async function fetchJournalDays(initDataRaw: string, month: string): Promise<JournalDaysResponse> {
  return apiV2Get<JournalDaysResponse>(`/api/v2/journal/days?month=${month}`, initDataRaw);
}

/** 404 — чужая/несуществующая, 409 — небезопасно удалять (текст причины
 * человекочитаемый, приходит в Error.message). */
/** #263 — запись тренировки задним числом / свободной активности. 422 — невалидные
 * данные (будущая дата, длительность), 404 — чужое упражнение. */
export async function createSession(initDataRaw: string, payload: SessionCreatePayload): Promise<SessionResponseV2> {
  return apiV2Post<SessionCreatePayload, SessionResponseV2>("/api/v2/sessions", initDataRaw, payload);
}

export async function deleteSession(initDataRaw: string, sessionId: number): Promise<void> {
  return apiV2Delete(`/api/v2/sessions/${sessionId}`, initDataRaw);
}

/** PATCH /sessions/{id} (#262): незаданные поля не меняются; effort/comment = null
 * очищают; performed_on — локальный день (не в будущем). 404 — чужая, 409 — не
 * проходит предикат безопасности (причина в Error.message), 422 — валидация. */
export interface SessionEditRequestV2 {
  performed_on?: string;
  effort?: string | null;
  comment?: string | null;
  sets: { block_index: number; set_number: number; value: string; effort: string | null; note: string | null }[];
}

export async function editSession(
  initDataRaw: string, sessionId: number, body: SessionEditRequestV2,
): Promise<SessionResponseV2> {
  return apiV2Patch(`/api/v2/sessions/${sessionId}`, initDataRaw, body);
}

/** POST /sessions/{id}/clone (#262): новая завершённая сессия; performed_on по умолчанию — сегодня. */
export async function cloneSession(
  initDataRaw: string, sessionId: number, performedOn?: string,
): Promise<SessionResponseV2> {
  return apiV2Post(`/api/v2/sessions/${sessionId}/clone`, initDataRaw, performedOn ? { performed_on: performedOn } : {});
}

// --- Каталог программ (Capability A, issue #188) — GET /programs список,
// POST /program-inclusions добавляет курс в единственный TrainingPlan
// пользователя. Схемы полей зеркалят app/web/schemas_v2.py::ProgramResponse/
// ProgramInclusionCreateRequest один в один, не выдумывать лишних полей. ---

export interface ProgramResponseV2 {
  id: number;
  name: string;
  goal: string;
  structure_type: string;
  category: string | null;
  progression_strategy_type: string | null;
}

export async function fetchPrograms(initDataRaw: string): Promise<ProgramResponseV2[]> {
  const response = await apiV2Get<{ programs: ProgramResponseV2[] }>("/api/v2/programs", initDataRaw);
  return response.programs;
}

export async function createProgramInclusion(
  initDataRaw: string, programId: number,
): Promise<ProgramInclusionResponseV2> {
  return apiV2Post("/api/v2/program-inclusions", initDataRaw, { program_id: programId });
}

/** issue #266 — «Убрать курс из плана»: is_active=false, история остаётся. */
export async function deactivateProgramInclusion(
  initDataRaw: string, inclusionId: number,
): Promise<ProgramInclusionResponseV2> {
  return apiV2Post(`/api/v2/program-inclusions/${inclusionId}/deactivate`, initDataRaw, {});
}

/** issue #266 — превью структуры программы (зеркало ProgramScheduleResponse). */
export interface ProgramScheduleItemV2 {
  week_phase: string;
  day_of_week: number | null;
  count_per_week: number;
  title: string;
  count_label: string;
  target_label: string | null;
}

export interface ProgramScheduleV2 {
  program_id: number;
  duration_weeks: number | null;
  phases: string[];
  items: ProgramScheduleItemV2[];
}

export async function fetchProgramSchedule(initDataRaw: string, programId: number): Promise<ProgramScheduleV2> {
  return apiV2Get(`/api/v2/programs/${programId}/schedule`, initDataRaw);
}

// --- POST /plan-items — создание manual PlanItem (issue #197, Checkpoint 3B) ---

export interface PlanItemCreateRequest {
  count_per_week: number;
  exercise_id?: number;
  complex_id?: number;
  day_of_week?: number | null;
  week_phase?: "base" | "rest" | "peak" | null;
  plan_week_id?: number | null;
}

export async function createPlanItem(
  initDataRaw: string,
  request: PlanItemCreateRequest,
): Promise<PlanItemResponseV2> {
  return apiV2Post("/api/v2/plan-items", initDataRaw, request);
}

/** Phase D3 (issue #188) — под уже существующий D2 PATCH /plan-items/{id}.
 * dayOfWeek: number (0=Пн..6=Вс) | null (свободный пул) — поле обязательно
 * на backend-стороне (PlanItemMoveRequest без default), явная передача
 * null здесь так же обязательна, не опускается. */
export async function movePlanItem(
  initDataRaw: string, planItemId: number, dayOfWeek: number | null,
): Promise<PlanItemResponseV2> {
  return apiV2Patch<{ day_of_week: number | null }, PlanItemResponseV2>(
    `/api/v2/plan-items/${planItemId}`, initDataRaw, { day_of_week: dayOfWeek },
  );
}

/** Phase D3 (issue #188) — под уже существующий D2 DELETE /plan-items/{id}. */
export async function removePlanItem(initDataRaw: string, planItemId: number): Promise<void> {
  return apiV2Delete(`/api/v2/plan-items/${planItemId}`, initDataRaw);
}

// --- Analytics v2: GET /api/v2/analytics/training (REBUILD-1, R3) ---------------------
// Отдельный конвейер завершённых TrainingSession, считается на бэкенде по ВСЕМ
// сессиям пользователя (не выводится из страниц Журнала).

export interface AnalyticsWeekV2 {
  week_start: string;
  sessions: number;
  active_days: number;
}

export interface AnalyticsPointV2 {
  at: string;
  value: string;
  best: string | null;
  cumulative_best: string | null;
  is_new_pb: boolean | null;
  cycles: number | null;
}

export interface AnalyticsPanelV2 {
  protocol_type: ProtocolType;
  session_count: number;
  /** "reps" | "s"; null у interval. */
  unit: string | null;
  total_reps: string | null;
  total_work_seconds: string | null;
  set_count: number | null;
  best_set: string | null;
  attempt_count: number | null;
  best: string | null;
  actual_duration_seconds: number | null;
  cycles: number | null;
  points: AnalyticsPointV2[];
  /** Сколько точек всего (в points — не больше 200 последних). */
  points_total: number;
}

export interface AnalyticsExerciseV2 {
  exercise_id: number;
  exercise_name: string;
  panels: AnalyticsPanelV2[];
}

export interface AnalyticsMetricWeekV2 {
  /** Понедельник недели (локальная дата пользователя). */
  week_start: string;
  workouts: number;
  /** Целые минуты; тренировки без валидной длительности не входят. */
  minutes: number;
}

export interface AnalyticsMetricsV2 {
  date_from: string;
  date_to: string;
  weeks: AnalyticsMetricWeekV2[];
  total_workouts: number;
  total_minutes: number;
  /** Тренировки диапазона без данных о времени (в минуты не входят). */
  without_duration: number;
}

export interface TrainingAnalyticsV2 {
  timezone: string;
  metrics: AnalyticsMetricsV2;
  activity: {
    sessions_last_30_days: number;
    active_days_last_30_days: number;
    weeks: AnalyticsWeekV2[];
  };
  exercises: AnalyticsExerciseV2[];
}

/** Без range — сервер берёт последние 30 локальных дней (пресет «1 мес»). */
export async function fetchTrainingAnalytics(
  initDataRaw: string, range?: { from: string; to: string },
): Promise<TrainingAnalyticsV2> {
  const query = range ? `?from=${range.from}&to=${range.to}` : "";
  return apiV2Get<TrainingAnalyticsV2>(`/api/v2/analytics/training${query}`, initDataRaw);
}

// --- Тесты (Assessment Tests, #260): протоколы и свои замеры, вне прогрессии ---------------

export interface AssessmentResultV2 {
  id: number;
  protocol_id: number;
  performed_on: string; // YYYY-MM-DD
  value: string;
  unit: string;
  note: string | null;
}

export interface AssessmentProtocolV2 {
  id: number;
  name: string;
  description: string | null;
  metric_type: string;
  unit: string;
  last_result: AssessmentResultV2 | null;
  results_count: number;
  trend: string[]; // старые → новые
}

export async function listAssessments(initDataRaw: string): Promise<AssessmentProtocolV2[]> {
  const response = await apiV2Get<{ protocols: AssessmentProtocolV2[] }>("/api/v2/assessments", initDataRaw);
  return response.protocols;
}

export async function getAssessment(
  initDataRaw: string, protocolId: number,
): Promise<{ protocol: AssessmentProtocolV2; results: AssessmentResultV2[] }> {
  return apiV2Get(`/api/v2/assessments/${protocolId}/results`, initDataRaw);
}

export interface AssessmentResultInput {
  performed_on: string;
  value: number;
  note: string | null;
}

export async function createAssessmentResult(
  initDataRaw: string, protocolId: number, input: AssessmentResultInput,
): Promise<AssessmentResultV2> {
  return apiV2Post<AssessmentResultInput, AssessmentResultV2>(
    `/api/v2/assessments/${protocolId}/results`, initDataRaw, input,
  );
}

export async function updateAssessmentResult(
  initDataRaw: string, resultId: number, input: AssessmentResultInput,
): Promise<AssessmentResultV2> {
  return apiV2Patch<AssessmentResultInput, AssessmentResultV2>(
    `/api/v2/assessments/results/${resultId}`, initDataRaw, input,
  );
}

export async function deleteAssessmentResult(initDataRaw: string, resultId: number): Promise<void> {
  return apiV2Delete(`/api/v2/assessments/results/${resultId}`, initDataRaw);
}
