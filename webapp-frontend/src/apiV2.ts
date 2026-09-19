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

export async function fetchDashboardStatus(initDataRaw: string): Promise<DashboardStatusResponse> {
  return apiV2Get<DashboardStatusResponse>("/api/v2/dashboard/status", initDataRaw);
}
