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

/** Один пункт личного списка резин пользователя (issue #48) — тот же
 * источник, что бот показывает при "✏️ Изменить вес/резину"
 * (app/bot/keyboards.py::band_item_picker_keyboard). */
export interface BandItemInfo {
  id: number;
  name: string;
  resistance_kg: string | null;
}

/** GET /api/workout/plan (issue #36, Этап 1) — status="ready" — единственный
 * случай, когда поля target/work_sets/equipment заполнены; любой другой
 * статус — та же причина, что определила бы ветку в handle_start_workout
 * бота (app/bot/handlers/workout.py), форма не показывается.
 *
 * band_items заполнен, только если равнозначный выбор резины возможен хотя
 * бы для одного блока (equipment_a/b.type === "band"), иначе пуст. */
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
  band_items: BandItemInfo[];
}

export interface AnomalyFlags {
  large_value: number | null;
  previous_avg: number | null;
  current_avg: number | null;
  expected_set_count: number | null;
  actual_set_count: number | null;
}

/** Один пункт списка ачивок (issue #66, п.1) — code для стабильного
 * сопоставления (иконка/сортировка), label — уже готовый текст с бэкенда
 * (app.domain.achievements.ACHIEVEMENT_LABELS, тот же, что видит пользователь
 * бота), unlocked_at — "YYYY-MM-DD". */
export interface AchievementItem {
  code: string;
  label: string;
  unlocked_at: string;
}

/** Вкладка "Профиль" (issue #45, часть 3) — узкий срез того, что показывает
 * app.bot.handlers.menu.render_profile (та же format_subscription_status на
 * бэкенде, не отдельный текст). is_onboarded=false — остальные поля пустые,
 * тот же принцип, что у HelloResponse. achievements (issue #66, п.1) — то же
 * число, что achievements_count, только с деталями для кликабельного счётчика. */
export interface ProfileResponse {
  is_onboarded: boolean;
  subscription_status_label: string | null;
  coins_balance: number | null;
  achievements_count: number | null;
  achievements: AchievementItem[];
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
  /** Выбор резины (issue #48) — тот же принцип, что actual_weight выше,
   * только для BAND и id из band_items вместо числа. Игнорируется на
   * бэкенде, если снаряд блока не BAND (см. app/web/routes.py::submit_workout). */
  block_a_actual_band_item_id?: number | null;
  block_b_actual_band_item_id?: number | null;
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

/** GET /api/gto (issue #71) — разряд ГТО по подтягиванию, отдельная
 * концепция от списка ачивок (AchievementItem выше): статус, не факт
 * истории, пересчитывается на лету при каждом запросе (не хранится в БД,
 * см. app/domain/gto.py — снижение результата или смена возрастной
 * ступени меняют его в обе стороны).
 *
 * applicable=false — показывать нечего, reason объясняет почему:
 * "not_onboarded"/"missing_birth_date" — профиль не заполнен;
 * "only_male" — доступно только для мужского пола (женский норматив ГТО
 * измеряет другое упражнение — вис лёжа на низкой перекладине, не
 * сопоставим с обычными подтягиваниями на высокой, которые тренирует это
 * приложение); "age_out_of_range" — младше 18; "norm_data_missing" —
 * официальные нормативы для этой возрастной ступени ещё не подтверждены;
 * "no_workouts" — ещё нет ни одной тренировки. rank/next_rank —
 * "none"|"bronze"|"silver"|"gold", next_rank отсутствует уже на "gold". */
export interface GtoStatus {
  applicable: boolean;
  reason: string | null;
  age: number | null;
  step_number: number | null;
  rank: string | null;
  best_max_reps: number | null;
  bronze_threshold: number | null;
  silver_threshold: number | null;
  gold_threshold: number | null;
  next_rank: string | null;
  reps_to_next_rank: number | null;
}

export async function fetchGtoStatus(initDataRaw: string): Promise<GtoStatus> {
  return apiGet<GtoStatus>("/api/gto", initDataRaw);
}

/** Одна тренировка в списке "История" (issue #50, волна 1) — те же факты,
 * что печатает бот в app.bot.handlers.history.format_history_entry, только
 * структурированные под карточку. target_a/target_b заполнены только у
 * самой свежей записи во всей истории. */
export interface HistoryEntry {
  workout_id: number;
  performed_at: string;
  is_backdated: boolean;
  comment: string | null;
  equipment_a: EquipmentInfo;
  equipment_b: EquipmentInfo;
  result_a: string;
  result_b: string;
  target_a: number | null;
  target_b: number | null;
}

export interface HistoryPage {
  items: HistoryEntry[];
  has_more: boolean;
}

/** Одна точка графика "Прогресс" (issue #50, волна 2) — цель за подход
 * блока A/Б на момент этой тренировки, уже посчитанная прогрессией на
 * бэкенде (app/web/routes.py::get_progress), не пересчитывается на клиенте. */
export interface ProgressPoint {
  performed_at: string;
  target_a: number;
  target_b: number;
  workout_set_id: number | null;
}

export interface ProgressData {
  points: ProgressPoint[];
}

export async function fetchHistory(initDataRaw: string, offset: number, limit = 20): Promise<HistoryPage> {
  return apiGet<HistoryPage>(`/api/history?offset=${offset}&limit=${limit}`, initDataRaw);
}

export async function fetchProgress(initDataRaw: string): Promise<ProgressData> {
  return apiGet<ProgressData>("/api/progress", initDataRaw);
}

/** Зеркало app.domain.reports.WeeklySummary (issue #66, п.2) — та же
 * недельная сводка, что показывает кнопка "📊 Прогресс" бота. */
export interface WeeklySummary {
  workout_count: number;
  total_volume: number;
  volume_change_pct: number | null;
  equipment_changed_a: boolean;
  equipment_changed_b: boolean;
}

/** Зеркало app.domain.reports.EquipmentProgress — динамика объёма на
 * текущем снаряде блока A/Б ("с этой резиной делал 40, сейчас 80"). */
export interface EquipmentProgress {
  equipment: EquipmentInfo;
  first_volume: number;
  current_volume: number;
  change_pct: number | null;
}

/** Зеркало app.domain.reports.CycleVolume — одна строка "📈 Аналитика по
 * всем циклам" бота. */
export interface CycleVolume {
  workout_set_id: number;
  workout_count: number;
  total_volume: number;
  volume_change_pct: number | null;
}

/** GET /api/analytics (issue #66, п.2) — те же вызовы app.domain.reports с
 * теми же входными данными, что и кнопки "📊 Прогресс"/"📈 Аналитика по всем
 * циклам" бота, просто в JSON вместо готового текста. has_data=false — та же
 * "истории пока нет", что и у пустого графика /api/progress. */
export interface AnalyticsData {
  has_data: boolean;
  weekly: WeeklySummary | null;
  equipment_progress_a: EquipmentProgress | null;
  equipment_progress_b: EquipmentProgress | null;
  total_volume: number | null;
  cycle_count: number | null;
  cycles: CycleVolume[];
}

export async function fetchAnalytics(initDataRaw: string): Promise<AnalyticsData> {
  return apiGet<AnalyticsData>("/api/analytics", initDataRaw);
}

/** Раздел подписки/оплаты (issue #53, волна 1) — расширяет то, что уже
 * частично видно во вкладке "Профиль" (см. ProfileResponse выше), тем же
 * status_label с бэкенда (app.bot.formatting.format_subscription_status,
 * не отдельный текст на фронтенде). price_rub/days/pricing_text_html/
 * robokassa_available не зависят от пользователя — те же значения, что
 * паивелл бота (app/bot/texts.py::PRICING_TEXT), отдаются даже
 * неонбордившемуся. pricing_text_html — HTML, источник полностью
 * статический (не пользовательский ввод), безопасен для
 * dangerouslySetInnerHTML. */
export interface SubscriptionResponse {
  is_onboarded: boolean;
  status: string | null;
  status_label: string | null;
  expires_at: string | null;
  price_rub: number;
  days: number;
  pricing_text_html: string;
  robokassa_available: boolean;
}

export interface PaymentLinkResponse {
  payment_url: string;
}

export async function fetchSubscription(initDataRaw: string): Promise<SubscriptionResponse> {
  return apiGet<SubscriptionResponse>("/api/subscription", initDataRaw);
}

export async function paySubscription(initDataRaw: string): Promise<PaymentLinkResponse> {
  const response = await fetch("/api/subscription/pay", {
    method: "POST",
    headers: { "X-Telegram-Init-Data": initDataRaw },
  });
  if (!response.ok) {
    throw new Error(`POST /api/subscription/pay failed: ${response.status}`);
  }
  return (await response.json()) as PaymentLinkResponse;
}

async function apiPost<TBody, TResult>(path: string, initDataRaw: string, body: TBody): Promise<TResult> {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "X-Telegram-Init-Data": initDataRaw,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`POST ${path} failed: ${response.status}`);
  }
  return (await response.json()) as TResult;
}

export async function submitWorkout(
  initDataRaw: string,
  body: WorkoutSubmitRequest,
): Promise<WorkoutSubmitResponse> {
  return apiPost<WorkoutSubmitRequest, WorkoutSubmitResponse>("/api/workout/submit", initDataRaw, body);
}

/** Детали одной тренировки для формы редактирования (issue #52) — тот же
 * набор фактов, что app.bot.handlers.workout_edit::_start_editing кладёт в
 * FSM перед переспросом блока A. target_before — цель, от которой реально
 * считался ввод этой тренировки, не текущая цель пользователя. */
export interface HistoryBlockDetail {
  working_reps: number[];
  max_reps: number;
  target_before: number;
  equipment: EquipmentInfo;
}

export interface HistoryEditDetail {
  workout_id: number;
  performed_at: string;
  is_editable: boolean;
  comment: string | null;
  block_a: HistoryBlockDetail;
  block_b: HistoryBlockDetail;
}

/** PATCH /api/history/{id} — то же тело, что WorkoutSubmitRequest минус
 * comment (правка комментария не входит в этот сценарий ни у бота, ни
 * здесь — см. app/web/routes.py::edit_history_workout). */
export interface HistoryEditRequest {
  block_a_working_reps: number[];
  block_a_max_reps: number;
  block_b_working_reps: number[];
  block_b_max_reps: number;
  block_a_actual_weight?: string | null;
  block_b_actual_weight?: string | null;
  block_a_actual_band_item_id?: number | null;
  block_b_actual_band_item_id?: number | null;
  confirm_anomalies: boolean;
}

export async function fetchHistoryDetail(initDataRaw: string, workoutId: number): Promise<HistoryEditDetail> {
  return apiGet<HistoryEditDetail>(`/api/history/${workoutId}`, initDataRaw);
}

export async function patchHistoryEdit(
  initDataRaw: string,
  workoutId: number,
  body: HistoryEditRequest,
): Promise<WorkoutSubmitResponse> {
  const response = await fetch(`/api/history/${workoutId}`, {
    method: "PATCH",
    headers: {
      "X-Telegram-Init-Data": initDataRaw,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`PATCH /api/history/${workoutId} failed: ${response.status}`);
  }
  return (await response.json()) as WorkoutSubmitResponse;
}

/** POST /api/workout/backdate — снаряд здесь ВСЕГДА явный (не наследуется
 * молча, в отличие от WorkoutSubmitRequest) — тот же принцип, что явный
 * переспрос снаряда у бота для бэкдейта (app/bot/handlers/backdate.py). */
export interface BackdateSubmitRequest {
  performed_at: string;
  block_a_working_reps: number[];
  block_a_max_reps: number;
  block_b_working_reps: number[];
  block_b_max_reps: number;
  block_a_equipment_type: string;
  block_a_equipment_value?: string | null;
  block_a_equipment_item_id?: number | null;
  block_b_equipment_type: string;
  block_b_equipment_value?: string | null;
  block_b_equipment_item_id?: number | null;
  confirm_anomalies: boolean;
}

export async function fetchBackdatePlan(initDataRaw: string): Promise<WorkoutPlanResponse> {
  return apiGet<WorkoutPlanResponse>("/api/workout/backdate/plan", initDataRaw);
}

export async function submitBackdate(
  initDataRaw: string,
  body: BackdateSubmitRequest,
): Promise<WorkoutSubmitResponse> {
  return apiPost<BackdateSubmitRequest, WorkoutSubmitResponse>("/api/workout/backdate", initDataRaw, body);
}

/** PUT /api/workout/draft (issue #61) — сохраняет накопленный прогресс
 * живой тренировки после каждого завершённого подхода, весь массив разом,
 * не по одному подходу. В отличие от WorkoutSubmitRequest working_reps
 * может быть короче итогового числа подходов и max_reps может отсутствовать
 * — черновик фиксирует промежуточное состояние, не готовую тренировку. */
export interface WorkoutDraftRequest {
  step_index: number;
  block_a_working_reps: number[];
  block_a_max_reps: number | null;
  block_b_working_reps: number[];
  block_b_max_reps: number | null;
  block_a_actual_weight?: string | null;
  block_b_actual_weight?: string | null;
  block_a_actual_band_item_id?: number | null;
  block_b_actual_band_item_id?: number | null;
  comment?: string | null;
}

/** GET/PUT/DELETE /api/workout/draft — active=false значит черновика нет
 * (обычный старт с "intro"), остальные поля заполнены только при
 * active=true (тот же принцип, что у TimerStatus). */
export interface WorkoutDraft {
  active: boolean;
  step_index: number | null;
  block_a_working_reps: number[] | null;
  block_a_max_reps: number | null;
  block_b_working_reps: number[] | null;
  block_b_max_reps: number | null;
  block_a_actual_weight: string | null;
  block_b_actual_weight: string | null;
  block_a_actual_band_item_id: number | null;
  block_b_actual_band_item_id: number | null;
  comment: string | null;
}

export async function fetchWorkoutDraft(initDataRaw: string): Promise<WorkoutDraft> {
  return apiGet<WorkoutDraft>("/api/workout/draft", initDataRaw);
}

export async function saveWorkoutDraft(initDataRaw: string, body: WorkoutDraftRequest): Promise<WorkoutDraft> {
  const response = await fetch("/api/workout/draft", {
    method: "PUT",
    headers: {
      "X-Telegram-Init-Data": initDataRaw,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`PUT /api/workout/draft failed: ${response.status}`);
  }
  return (await response.json()) as WorkoutDraft;
}

export async function deleteWorkoutDraft(initDataRaw: string): Promise<WorkoutDraft> {
  const response = await fetch("/api/workout/draft", {
    method: "DELETE",
    headers: { "X-Telegram-Init-Data": initDataRaw },
  });
  if (!response.ok) {
    throw new Error(`DELETE /api/workout/draft failed: ${response.status}`);
  }
  return (await response.json()) as WorkoutDraft;
}

/** Персистентный таймер режима тренировки в реальном времени (issue #59,
 * волна 1) — общий ответ POST /api/timer/start, GET /api/timer/status и
 * DELETE /api/timer. active=false покрывает и "таймера нет вообще", и
 * "таймер уже истёк" — remaining_seconds отличает эти случаи друг от друга
 * (см. app/web/routes.py::_timer_status_response), контекст (тип/блок/
 * подход) остаётся даже у истёкшего таймера, полей нет только когда
 * активного таймера не было НИКОГДА. */
export interface TimerStatus {
  active: boolean;
  timer_type: string | null;
  duration_seconds: number | null;
  remaining_seconds: number | null;
  block_letter: string | null;
  set_number: number | null;
}

export interface TimerStartRequest {
  timer_type: string;
  duration_seconds: number;
  block_letter?: string | null;
  set_number?: number | null;
}

export async function startTimer(initDataRaw: string, body: TimerStartRequest): Promise<TimerStatus> {
  return apiPost<TimerStartRequest, TimerStatus>("/api/timer/start", initDataRaw, body);
}

/** Источник правды — сервер: вызывается при каждом открытии/возврате в
 * приложение (visibilitychange/focus), не только один раз при старте
 * таймера — локальный setInterval между такими опросами только тикает
 * визуально, не считается сам по себе (issue #59). */
export async function fetchTimerStatus(initDataRaw: string): Promise<TimerStatus> {
  return apiGet<TimerStatus>("/api/timer/status", initDataRaw);
}

export async function cancelTimer(initDataRaw: string): Promise<TimerStatus> {
  const response = await fetch("/api/timer", {
    method: "DELETE",
    headers: { "X-Telegram-Init-Data": initDataRaw },
  });
  if (!response.ok) {
    throw new Error(`DELETE /api/timer failed: ${response.status}`);
  }
  return (await response.json()) as TimerStatus;
}

/** Персистентные настройки длительности таймера (issue #59, волна 2) —
 * значения уже резолвлены дефолтом на бэкенде (240/180/900с), фронтенду не
 * нужно знать про дефолты отдельно. */
export interface TimerPreferences {
  rest_seconds_block_a: number;
  rest_seconds_block_b: number;
  big_break_seconds: number;
}

export interface TimerPreferencesUpdateRequest {
  block_letter?: "A" | "B" | null;
  duration_seconds: number;
}

export async function fetchTimerPreferences(initDataRaw: string): Promise<TimerPreferences> {
  return apiGet<TimerPreferences>("/api/timer/preferences", initDataRaw);
}

export async function updateTimerPreferences(
  initDataRaw: string,
  body: TimerPreferencesUpdateRequest,
): Promise<TimerPreferences> {
  const response = await fetch("/api/timer/preferences", {
    method: "PUT",
    headers: {
      "X-Telegram-Init-Data": initDataRaw,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`PUT /api/timer/preferences failed: ${response.status}`);
  }
  return (await response.json()) as TimerPreferences;
}

/** Три переключаемые метрики лидерборда (issue #67) — вкладки одного
 * экрана, не три отдельных. */
export type LeaderboardMetric = "max_reps" | "max_weight" | "total_volume";
export type LeaderboardGender = "all" | "male" | "female";
/** Период для метрики "объём" (issue #74, волна 2) — скользящее окно
 * (последние 7/30 дней от текущего момента), не календарное с
 * понедельника/1 числа. Игнорируется бэкендом для max_reps/max_weight (это
 * разовые рекорды, не сумма за интервал), поэтому фронтенд не показывает
 * переключатель на других вкладках (см. METRIC_TABS ниже). */
export type LeaderboardPeriod = "week" | "month" | "all";
/** Ступени ГТО для взрослых (см. app.domain.leaderboard.AGE_BUCKETS) —
 * "all" здесь и на бэкенде означает "без фильтра по возрасту". */
export type LeaderboardAgeBucket = "all" | "18_29" | "30_39" | "40_49" | "50_59" | "60_69" | "70_plus";

/** Одна строка лидерборда — display_name уже "Аноним" вместо null (веб-роут
 * подставляет текст сам, см. app/web/routes.py). */
export interface LeaderboardEntry {
  rank: number;
  display_name: string;
  value: string;
  is_current_user: boolean;
}

/** GET /api/leaderboard — entries содержит топ-N плюс, если он вне топа,
 * отдельной строкой в конце — самого запрашивающего пользователя
 * (is_current_user=true у ровно одной строки, либо ни у одной).
 * my_display_name — текущая настройка имени для поля ввода на этом же
 * экране. */
export interface LeaderboardData {
  metric: LeaderboardMetric;
  entries: LeaderboardEntry[];
  my_display_name: string | null;
  my_rank: number | null;
}

export async function fetchLeaderboard(
  initDataRaw: string,
  metric: LeaderboardMetric,
  gender: LeaderboardGender,
  ageBucket: LeaderboardAgeBucket,
  period: LeaderboardPeriod = "all",
): Promise<LeaderboardData> {
  return apiGet<LeaderboardData>(
    `/api/leaderboard?metric=${metric}&gender=${gender}&age_bucket=${ageBucket}&period=${period}`,
    initDataRaw,
  );
}

export async function updateLeaderboardDisplayName(
  initDataRaw: string,
  displayName: string | null,
): Promise<{ display_name: string | null }> {
  const response = await fetch("/api/leaderboard/display-name", {
    method: "PUT",
    headers: {
      "X-Telegram-Init-Data": initDataRaw,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ display_name: displayName }),
  });
  if (!response.ok) {
    throw new Error(`PUT /api/leaderboard/display-name failed: ${response.status}`);
  }
  return (await response.json()) as { display_name: string | null };
}
