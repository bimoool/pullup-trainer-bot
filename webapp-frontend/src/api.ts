export interface HelloResponse {
  name: string;
  is_onboarded: boolean;
  readiness_status: string | null;
  days_since_last_workout: number | null;
}

export interface EquipmentInfo {
  type: string;
  value: string | null;
  item_id: number | null;
  label: string;
}

/** GET /api/workout/plan (issue #36, Этап 1) — status="ready" — единственный
 * случай, когда поля target/work_sets/equipment заполнены; любой другой
 * статус — та же причина, что определила бы ветку в handle_start_workout
 * бота (app/bot/handlers/workout.py), форма не показывается. */
export interface WorkoutPlanResponse {
  status: string;
  workout_set_id: number | null;
  target_a: number | null;
  target_b: number | null;
  work_sets_a: number | null;
  work_sets_b: number | null;
  equipment_a: EquipmentInfo | null;
  equipment_b: EquipmentInfo | null;
  is_gap_rollback: boolean;
}

export interface AnomalyFlags {
  large_value: number | null;
  previous_avg: number | null;
  current_avg: number | null;
  expected_set_count: number | null;
  actual_set_count: number | null;
}

/** Вкладка "Профиль" (issue #45, часть 3) — узкий срез того, что показывает
 * app.bot.handlers.menu.render_profile (та же format_subscription_status на
 * бэкенде, не отдельный текст). is_onboarded=false — остальные поля пустые,
 * тот же принцип, что у HelloResponse. */
export interface ProfileResponse {
  is_onboarded: boolean;
  subscription_status_label: string | null;
  coins_balance: number | null;
  achievements_count: number | null;
  workouts_count: number | null;
  days_since_last_workout: number | null;
}

export interface WorkoutSubmitRequest {
  block_a_working_reps: number[];
  block_a_max_reps: number;
  block_b_working_reps: number[];
  block_b_max_reps: number;
  /** Необязательная правка веса на месте (issue #45, часть 2) — тот же
   * смысл, что "✏️ Изменить вес/резину" в боте. Имеет эффект на бэкенде,
   * только если снаряд соответствующего блока реально WEIGHT (см.
   * app/web/routes.py::submit_workout) — для BAND/BODYWEIGHT/AUSTRALIAN
   * значение молча игнорируется. */
  block_a_actual_weight?: string | null;
  block_b_actual_weight?: string | null;
  comment: string | null;
  confirm_anomalies: boolean;
}

export interface WorkoutSubmitResponse {
  status: string;
  target_a: number | null;
  target_b: number | null;
  equipment_a: EquipmentInfo | null;
  equipment_b: EquipmentInfo | null;
  result_a: string | null;
  result_b: string | null;
  anomalies_a: AnomalyFlags | null;
  anomalies_b: AnomalyFlags | null;
}

/**
 * Один origin с бэкендом (см. app/web/main.py — та же FastAPI-статика),
 * поэтому относительный путь без CORS. initDataRaw — сырая, не
 * распарсенная на клиенте query-string (см. app/web/auth.py: доверять
 * можно только тому, что бэкенд сам проверил подписью).
 */
async function apiGet<T>(path: string, initDataRaw: string): Promise<T> {
  const response = await fetch(path, {
    headers: { "X-Telegram-Init-Data": initDataRaw },
  });
  if (!response.ok) {
    throw new Error(`GET ${path} failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchHello(initDataRaw: string): Promise<HelloResponse> {
  return apiGet<HelloResponse>("/api/hello", initDataRaw);
}

export async function fetchWorkoutPlan(initDataRaw: string): Promise<WorkoutPlanResponse> {
  return apiGet<WorkoutPlanResponse>("/api/workout/plan", initDataRaw);
}

export async function fetchProfile(initDataRaw: string): Promise<ProfileResponse> {
  return apiGet<ProfileResponse>("/api/profile", initDataRaw);
}

export async function submitWorkout(
  initDataRaw: string,
  body: WorkoutSubmitRequest,
): Promise<WorkoutSubmitResponse> {
  const response = await fetch("/api/workout/submit", {
    method: "POST",
    headers: {
      "X-Telegram-Init-Data": initDataRaw,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`POST /api/workout/submit failed: ${response.status}`);
  }
  return (await response.json()) as WorkoutSubmitResponse;
}
