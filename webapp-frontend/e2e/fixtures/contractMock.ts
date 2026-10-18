import type { Page } from "@playwright/test";

/**
 * CONTRACT_A_B v1 — слой-имитация серверных полей, пока ветка исполнителя A не интегрирована.
 *
 * Перехватывает GET /api/v2/plan, берёт НАСТОЯЩИЙ ответ локального стенда и достраивает недостающие поля
 * контракта (start_allowed, blocked_reason, session_variant/_basis, session_ordinal, inclusion.schedule).
 * Поля, которые сервер уже отдаёт, не перезаписываются. Включается явно; после интеграции A спеки идут
 * без него (E2E_REAL_CONTRACT=1 отключает перехват целиком).
 */
export interface ContractMockOptions {
  /** Подмена расписания подключения (форма CONTRACT §2) — например, «устаревшее, 3 в неделю, вмещается 2». */
  schedule?: {
    sessions_per_week: number;
    source: "snapshot" | "catalogue";
    is_legacy: boolean;
    min_days_between_starts: number;
    weekly_capacity: number;
  };
}

type Json = Record<string, unknown>;

export function realContractRequested(): boolean {
  return process.env.E2E_REAL_CONTRACT === "1";
}

export async function mockPlanContract(page: Page, options: ContractMockOptions = {}): Promise<void> {
  if (realContractRequested()) {
    return;
  }
  await page.route("**/api/v2/plan", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    const body = (await response.json()) as { plan: Json | null };
    const plan = body.plan;
    if (plan) {
      const items = (plan.plan_items as Json[]) ?? [];
      for (const item of items) {
        const state = (item.state as string | null) ?? null;
        const isOccurrence = item.occurrence_index !== null && item.occurrence_index !== undefined;
        if (item.start_allowed === undefined) {
          item.start_allowed = !(state === "too_early" || state === "infeasible" || state === "completed" || state === "missed");
        }
        if (item.blocked_reason === undefined) {
          item.blocked_reason = item.start_allowed ? null : state;
        }
        if (isOccurrence && item.program_inclusion_id !== null && item.session_variant === undefined) {
          item.session_variant = (item.occurrence_index as number) % 2 === 1 ? "A" : "B";
          item.session_variant_basis = "projected";
          item.session_ordinal = item.occurrence_index;
        }
      }
      for (const inclusion of (plan.program_inclusions as Json[]) ?? []) {
        if (inclusion.schedule === undefined && options.schedule) {
          inclusion.schedule = options.schedule;
        }
      }
    }
    await route.fulfill({ response, json: body });
  });
}
