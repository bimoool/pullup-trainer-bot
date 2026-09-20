import { Button, Section, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  fetchDashboardStatus,
  fetchPlan,
  startLiveSession,
  type DashboardBlockResponse,
  type LiveSessionResponse,
  type ProgramInclusionResponseV2,
  type TrainingPlanResponseV2,
} from "./apiV2";

type Props = {
  initDataRaw: string;
  onStarted: (session: LiveSessionResponse) => void;
  onGoToWorkout: () => void;
  /** Checkpoint 4A (issue #188) — явный набор PlanItem с карточки PlanWeek
   * ("Планы" → группа "Подтягивания" → "Начать"), той же группирующей
   * семантики (program_inclusion_id, day_of_week), что DashboardScreen.tsx
   * ::groupPlanItems уже применяет для отображения. Когда передан —
   * ЗАМЕНЯЕТ результат planItemIdsForInclusion ниже (Dashboard уже знает
   * точную группу, пересчитывать её здесь заново по exercise/category не
   * нужно — раздел 5 задачи), но НЕ отменяет STEP readiness-проверку
   * (dashboard/status, too_early/gap_retest_required остаются как есть,
   * раздел 6) — она не зависит от того, откуда взялись id, только от
   * состояния прогрессии пользователя. Admin-стенд (SessionV2Lab) не
   * передаёт этот проп — сохраняет старое поведение автопоиска. */
  planItemIds?: number[];
};

/**
 * Пред-экран сессии (issue #185, раздел 10.7 docs/plan-and-specs.md).
 *
 * Машина состояний (раздел 11): READY/BLOCKED/WARNED/NEEDS_ASSESSMENT из
 * IDLE. Готовность считается по-разному в зависимости от типа активного
 * курса — ни Program, ни ProgramInclusion НЕ несут поля rest_policy
 * ("жёсткая"/"мягкая", раздел 10.7): это отдельная продуктовая доработка
 * модели, не сделанная ни в одной из волн 0-5 (проверено: `grep -rn
 * rest_policy app/` пусто), и не придумывается здесь молча:
 *  - STEP-курс (подтягивания) — читает тот же GET /api/v2/dashboard/status,
 *    что DashboardV2Screen.tsx (не второй источник статуса), с теми же
 *    двумя реальными сигналами: "ready" (READY, с целями по блокам) и
 *    "too_early"/"gap_retest_required". "too_early" рисуется как BLOCKED
 *    без обхода (WARNED/"мягкая" здесь не реализован — тем же смыслом, что
 *    и старая схема, app/web/routes_v2_dashboard.py уже вела себя так же).
 *    "gap_retest_required" рисуется как NEEDS_ASSESSMENT: свой экран теста
 *    (GET/POST /assessments) не реализован ни в одной волне — кнопка ведёт
 *    в проверенный старый экран "Тренировка" (там есть путь повторного
 *    замера), не в тупик — тот же приём, что onGoToWorkout в
 *    DashboardV2Screen.tsx.
 *  - Курс БЕЗ STEP-стратегии (комплексы и т.п., см.
 *    app.services.live_session._resolve_complex_blocks) — dashboard/status
 *    его не поддерживает вовсе (отдаёт "not_migrated", раздел
 *    app/web/schemas_v2_dashboard.py), и никакой readiness-проверки для
 *    таких курсов в бэкенде в принципе не существует ни для одной волны
 *    (`grep -rn check_training_readiness app/services/live_session.py`
 *    пусто) — READY безусловно, все PlanItem активной инклюзии сразу.
 */

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "no_course" }
  | { phase: "blocked" }
  | { phase: "needs_assessment" }
  | { phase: "ready_step"; blockA: DashboardBlockResponse; blockB: DashboardBlockResponse; programName: string | null; planItemIds: number[] }
  | { phase: "ready_generic"; programName: string; planItemIds: number[] }
  | { phase: "starting"; planItemIds: number[] };

function BlockTargetCard({ letter, block }: { letter: "A" | "Б"; block: DashboardBlockResponse }) {
  return (
    <Section className="block-section" header={`Блок ${letter} — цель ${block.target}`}>
      <p className="block-subtitle">
        {`${block.work_sets} рабочих ${block.work_sets === 1 ? "подход" : "подхода"}`} · {block.equipment.label}
      </p>
    </Section>
  );
}

function findActiveInclusion(plan: TrainingPlanResponseV2 | null): ProgramInclusionResponseV2 | null {
  if (plan === null) {
    return null;
  }
  const active = plan.program_inclusions.filter((i) => i.is_active);
  return active.length === 1 ? active[0] : null;
}

function planItemIdsForInclusion(plan: TrainingPlanResponseV2, inclusion: ProgramInclusionResponseV2): number[] {
  return plan.plan_items.filter((item) => item.program_inclusion_id === inclusion.id).map((item) => item.id);
}

export function SessionPreScreen({ initDataRaw, onStarted, onGoToWorkout, planItemIds: explicitPlanItemIds }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const plan = await fetchPlan(initDataRaw);
        const inclusion = findActiveInclusion(plan);
        if (plan === null || inclusion === null) {
          if (!cancelled) {
            setState({ phase: "no_course" });
          }
          return;
        }

        if (inclusion.progression_state["strategy_type"] !== "step") {
          if (!cancelled) {
            setState({
              phase: "ready_generic",
              programName: inclusion.program_name,
              planItemIds: explicitPlanItemIds ?? planItemIdsForInclusion(plan, inclusion),
            });
          }
          return;
        }

        const data = await fetchDashboardStatus(initDataRaw);
        if (cancelled) {
          return;
        }
        if (data.status === "ready" && data.block_a && data.block_b) {
          setState({
            phase: "ready_step", blockA: data.block_a, blockB: data.block_b, programName: data.program_name,
            planItemIds: explicitPlanItemIds ?? planItemIdsForInclusion(plan, inclusion),
          });
        } else if (data.status === "too_early") {
          setState({ phase: "blocked" });
        } else if (data.status === "gap_retest_required") {
          setState({ phase: "needs_assessment" });
        } else {
          setState({ phase: "no_course" });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  async function handleStart(planItemIds: number[]) {
    setState({ phase: "starting", planItemIds });
    try {
      if (planItemIds.length === 0) {
        setState({ phase: "error", message: "Не удалось найти строки плана для сегодняшней сессии." });
        return;
      }
      const clientSessionId = crypto.randomUUID();
      const session = await startLiveSession(initDataRaw, clientSessionId, planItemIds);
      onStarted(session);
    } catch (error) {
      setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю пред-экран тренировки…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить: {state.message}</p>;
  }
  if (state.phase === "blocked") {
    return (
      <div>
        <p className="plan-title">Сессия (v2)</p>
        <p className="screen-message">
          Ещё рано для следующей тренировки — минимальный отдых между тренировками не прошёл.
        </p>
        <Button className="action-button" size="l" stretched onClick={onGoToWorkout}>
          Перейти в обычную "Тренировку"
        </Button>
      </div>
    );
  }
  if (state.phase === "needs_assessment") {
    return (
      <div>
        <p className="plan-title">Сессия (v2)</p>
        <p className="screen-message">Был долгий перерыв — сначала нужен повторный замер.</p>
        <Button className="action-button" size="l" stretched onClick={onGoToWorkout}>
          Пройти замер в обычной "Тренировке"
        </Button>
      </div>
    );
  }
  if (state.phase === "no_course") {
    return (
      <div>
        <p className="plan-title">Сессия (v2)</p>
        <p className="screen-message">Нет активного курса для этого экрана (или их больше одного).</p>
        <Button className="action-button" size="l" stretched onClick={onGoToWorkout}>
          Перейти в обычную "Тренировку"
        </Button>
      </div>
    );
  }

  const isStarting = state.phase === "starting";
  const step = state.phase === "ready_step" ? state : null;
  const generic = state.phase === "ready_generic" ? state : null;
  const planItemIds = step?.planItemIds ?? generic?.planItemIds ?? (state.phase === "starting" ? state.planItemIds : []);
  const programName = step?.programName ?? generic?.programName ?? null;

  return (
    <div>
      <p className="plan-title">Сессия (v2){programName ? ` — ${programName}` : ""}</p>
      {step && (
        <>
          <BlockTargetCard letter="A" block={step.blockA} />
          <BlockTargetCard letter="Б" block={step.blockB} />
        </>
      )}
      <Button
        className="action-button" size="l" stretched disabled={isStarting}
        onClick={() => void handleStart(planItemIds)}
      >
        {isStarting ? <Spinner size="s" /> : "Начать"}
      </Button>
    </div>
  );
}
