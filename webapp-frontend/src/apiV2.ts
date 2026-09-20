/**
 * Клиент для /api/v2/* (issue #167, волна 4) — отдельный от api.ts файл, тот
 * же принцип, что развёл app/web/schemas_v2.py от app/web/schemas.py на
 * бэкенде: v2-схема данных (TrainingPlan/ProgramInclusion/TrainingSession)
 * принципиально другая, не расширение старой. Единственный файл фронтенда
 * (вместе с DashboardScreen.tsx), которому разрешено упоминать /api/v2 — см.
 * allowlist в tests/test_web/test_v2_not_wired_to_ui.py.
 */

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
    throw new Error(`GET ${path} failed: ${response.status}`);
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
    throw new Error(`POST ${path} failed: ${response.status}`);
  }
  return (await response.json()) as TResult;
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

export interface LiveSessionResponse {
  id: number;
  client_session_id: string;
  status: "started" | "completed";
  phase: LiveSessionPhaseResponse;
  phase_index: number;
  current_block_index: number;
  current_set_number: number;
  blocks: LiveSessionBlockResponse[];
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

export async function completeLiveSession(
  initDataRaw: string,
  sessionId: number,
  abandoned: boolean,
): Promise<LiveSessionCompleteResponse> {
  return apiV2Post(`/api/v2/sessions/live/${sessionId}/complete`, initDataRaw, { abandoned });
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
  blocks: { order_index: number; exercise_id: number | null; complex_id: number | null; set_logs: SetLogResponseV2[] }[];
  progression_result: SessionProgressionResponseV2 | null;
  progression_skipped_reason: string | null;
}

export async function fetchSessions(initDataRaw: string, limit = 20): Promise<SessionResponseV2[]> {
  const response = await apiV2Get<{ sessions: SessionResponseV2[] }>(
    `/api/v2/sessions?limit=${limit}`, initDataRaw,
  );
  return response.sessions;
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
