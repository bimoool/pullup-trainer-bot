import { Button, Section, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  getWorkout,
  fetchDashboardStatus,
  fetchPlan,
  fetchActiveLiveSession,
  startLiveSession,
  startWorkoutLiveSession,
  type DashboardBlockResponse,
  type LiveSessionResponse,
  type ProgramInclusionResponseV2,
  type TrainingPlanResponseV2,
} from "./apiV2";
import { BackChevron } from "./BackChevron";
import { drainQueuedFinish } from "./offlineSession";
import { summarizeProtocol } from "./protocolConfig";
import { useBackButton } from "./useBackButton";
import { formatExerciseCount } from "./workoutCardFormat";
import { estimateWorkoutSeconds, formatEstimate } from "./workoutDetailFormat";

/** Потолок ожидания досылки старого завершения перед стартом (R-4): зависший запрос не должен вешать «Начать». */
const DRAIN_BEFORE_START_TIMEOUT_MS = 5_000;

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
  /** Checkpoint 4B (issue #188) — manual PlanItem (program_inclusion_id=NULL,
   * "Планка"/"Отжимания") не имеет ProgramInclusion вообще — весь STEP/
   * readiness-путь ниже (findActiveInclusion, fetchDashboardStatus)
   * структурно неприменим и упал бы в "no_course", ложно блокируя старт
   * тренировки без курса. manual=true пропускает этот путь целиком —
   * planItemIds обязателен вместе с ним (та же группа, что DashboardScreen
   * уже вычислил через groupPlanItems, не пересчитывается заново).
   * Program-backed путь (manual не передан) не изменён ни на строку. */
  manual?: boolean;
  /** Заголовок manual-сессии — то же group.title, что уже показывает
   * карточка на "Планах" ("Планка"/"Отжимания"), не пересчитывается
   * заново через Exercise Library здесь. */
  title?: string;
  /** «Начать» на Workout Detail: свободная сессия из своей тренировки без
   * PlanItem. Курс/readiness не применимы; если уже идёт другая живая
   * сессия — предлагаем продолжить её (одна активная сессия на пользователя). */
  workoutId?: number;
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
  | { phase: "loading"; title?: string }
  | { phase: "error"; message: string; title?: string }
  | { phase: "no_course"; title?: string }
  | { phase: "blocked"; title?: string }
  | { phase: "needs_assessment"; title?: string }
  | { phase: "ready_step"; blockA: DashboardBlockResponse; blockB: DashboardBlockResponse; programName: string | null; planItemIds: number[] }
  | { phase: "ready_generic"; programName: string; planItemIds: number[] }
  | { phase: "ready_manual"; title: string; planItemIds: number[] }
  | { phase: "starting"; planItemIds: number[]; title?: string };

function BlockTargetCard({ index, block }: { index: number; block: DashboardBlockResponse }) {
  return (
    <Section className="block-section" header={`Цель ${index}: ${block.target} повторений`}>
      <p className="block-subtitle">
        {`${block.work_sets} рабочих ${block.work_sets === 1 ? "подход" : "подхода"}`} · {block.equipment.label}
      </p>
    </Section>
  );
}

/** Шапка пред-экрана (#280): эйбрау + название — тот же язык, что у шапки Live Session. */
function PreHeader({ title, eyebrow = "Готовы к старту" }: { title: string; eyebrow?: string }) {
  return (
    <header className="pre-header">
      <p className="pre-eyebrow">{eyebrow}</p>
      <p className="plan-title pre-title">{title}</p>
    </header>
  );
}

/** Сводка перед стартом (#280): состав тренировки — упражнения с «подходы × повторы» и оценка длительности. */
type PreSummary = { meta: string; rows: { id: number; name: string; line: string }[] };

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

export function SessionPreScreen({
  initDataRaw, onStarted, onGoToWorkout, planItemIds: explicitPlanItemIds, manual, title, workoutId,
}: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  // Активная сессия, мешающая старту по workoutId: предлагаем её продолжить.
  const [activeConflict, setActiveConflict] = useState<LiveSessionResponse | null>(null);
  // Сводка — необязательная подсказка: любой сбой молча оставляет экран без неё.
  const [summary, setSummary] = useState<PreSummary | null>(null);

  // issue #202: Telegram BackButton — переиспользует существующий onGoToWorkout
  // (тот же хендлер, что у кнопок "Перейти в обычную Тренировку" в blocked/
  // needs_assessment/no_course фазах — не создаёт вторую логику выхода)
  useBackButton(onGoToWorkout, [onGoToWorkout], true, false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (workoutId !== undefined) {
        try {
          const active = await fetchActiveLiveSession(initDataRaw);
          if (cancelled) {
            return;
          }
          if (active !== null) {
            setActiveConflict(active);
          }
          setState({ phase: "ready_manual", title: title ?? "Тренировка", planItemIds: [] });
        } catch (error) {
          if (!cancelled) {
            setState({ phase: "error", message: error instanceof Error ? error.message : String(error), title });
          }
        }
        return;
      }
      // Manual-ветка (issue #188, Checkpoint 4B) — ни findActiveInclusion,
      // ни fetchDashboardStatus здесь не вызываются вообще: у manual
      // PlanItem нет ProgramInclusion, читать по нему readiness
      // невозможно и не нужно, это не тот же вопрос.
      if (manual) {
        if (!cancelled) {
          if (explicitPlanItemIds === undefined || explicitPlanItemIds.length === 0) {
            setState({ phase: "error", message: "Не удалось определить упражнение для тренировки.", title });
          } else {
            setState({ phase: "ready_manual", title: title ?? "Тренировка", planItemIds: explicitPlanItemIds });
          }
        }
        return;
      }

      try {
        const plan = await fetchPlan(initDataRaw);
        const inclusion = findActiveInclusion(plan);
        if (plan === null || inclusion === null) {
          if (!cancelled) {
            setState({ phase: "no_course", title });
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
          setState({ phase: "blocked", title: title ?? data.program_name ?? undefined });
        } else if (data.status === "gap_retest_required") {
          setState({ phase: "needs_assessment", title: title ?? data.program_name ?? undefined });
        } else {
          setState({ phase: "no_course", title: title ?? data.program_name ?? undefined });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error), title });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- explicitPlanItemIds/title стабильны на время жизни экрана (новый маунт на новый Start), пересчитывать по ним не нужно
  }, [initDataRaw, manual, workoutId]);

  useEffect(() => {
    let cancelled = false;
    async function loadSummary() {
      try {
        let complexId: number | null = null;
        if (workoutId !== undefined) {
          complexId = workoutId;
        } else if (manual && explicitPlanItemIds !== undefined && explicitPlanItemIds.length > 0) {
          const plan = await fetchPlan(initDataRaw);
          complexId = plan?.plan_items.find((item) => explicitPlanItemIds.includes(item.id) && item.complex_id !== null)?.complex_id ?? null;
        }
        if (complexId === null) {
          return;
        }
        const workout = await getWorkout(initDataRaw, complexId);
        const items = [...(workout.items ?? [])].sort((a, b) => a.order_index - b.order_index);
        if (cancelled || items.length === 0) {
          return;
        }
        const estimate = formatEstimate(estimateWorkoutSeconds(items));
        setSummary({
          meta: `${formatExerciseCount(items.length)}${estimate ? ` · ${estimate}` : ""}`,
          rows: items.map((item) => ({ id: item.id, name: item.exercise_name, line: summarizeProtocol(item.protocol).lines[0] })),
        });
      } catch {
        // без сводки экран остаётся рабочим
      }
    }
    void loadSummary();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- те же стабильные пропсы, что и у загрузки готовности выше
  }, [initDataRaw, manual, workoutId]);

  async function handleStart(planItemIds: number[], currentTitle?: string) {
    setState({ phase: "starting", planItemIds, title: currentTitle });
    try {
      // R-4 (#289): завершение прошлой сессии, оставленное в очереди, должно дойти до сервера ДО старта
      // новой — иначе старая ещё STARTED и сервер ответит 409. Best effort (офлайн/отказ — старт идёт
      // как раньше; очередь не трогаем), не дольше DRAIN_BEFORE_START_TIMEOUT_MS.
      await Promise.race([
        drainQueuedFinish(initDataRaw).catch(() => false),
        new Promise((resolve) => setTimeout(resolve, DRAIN_BEFORE_START_TIMEOUT_MS)),
      ]);
      if (workoutId !== undefined) {
        onStarted(await startWorkoutLiveSession(initDataRaw, crypto.randomUUID(), workoutId));
        return;
      }
      if (planItemIds.length === 0) {
        setState({ phase: "error", message: "Не удалось найти строки плана для сегодняшней сессии.", title: currentTitle });
        return;
      }
      const clientSessionId = crypto.randomUUID();
      const session = await startLiveSession(initDataRaw, clientSessionId, planItemIds);
      onStarted(session);
    } catch (error) {
      // 409 active_session_exists: на сервере уже идёт другая тренировка — тот же экран конфликта,
      // что и при заранее известной активной (продолжить текущую).
      if ((error as { status?: number }).status === 409) {
        try {
          const active = await fetchActiveLiveSession(initDataRaw);
          if (active !== null) {
            setActiveConflict(active);
            setState({ phase: "ready_manual", title: currentTitle ?? "Тренировка", planItemIds });
            return;
          }
        } catch {
          // не смогли узнать активную — показываем исходную ошибку ниже
        }
      }
      setState({ phase: "error", message: error instanceof Error ? error.message : String(error), title: currentTitle });
    }
  }

  if (state.phase === "loading") {
    const displayTitle = state.title ?? title ?? "Сессия";
    return <p className="screen-message">Загружаю {displayTitle.toLowerCase()}…</p>;
  }
  if (state.phase === "error") {
    const displayTitle = state.title ?? title ?? "Сессия";
    return (
      <div className="pre-screen">
        <PreHeader title={displayTitle} eyebrow="Тренировка" />
        <p className="screen-message">Не удалось загрузить: {state.message}</p>
      </div>
    );
  }
  if (state.phase === "blocked") {
    const displayTitle = state.title ?? title ?? "Сессия";
    return (
      <div className="pre-screen">
        <PreHeader title={displayTitle} eyebrow="Тренировка" />
        <p className="screen-message">
          Ещё рано для следующей тренировки — минимальный отдых между тренировками не прошёл.
        </p>
        <div className="pre-transport">
          <Button className="action-button vs-primary" size="l" stretched onClick={onGoToWorkout}>
            Перейти в обычную "Тренировку"
          </Button>
        </div>
      </div>
    );
  }
  if (state.phase === "needs_assessment") {
    const displayTitle = state.title ?? title ?? "Сессия";
    return (
      <div className="pre-screen">
        <PreHeader title={displayTitle} eyebrow="Тренировка" />
        <p className="screen-message">Был долгий перерыв — сначала нужен повторный замер.</p>
        <div className="pre-transport">
          <Button className="action-button vs-primary" size="l" stretched onClick={onGoToWorkout}>
            Пройти замер в обычной "Тренировке"
          </Button>
        </div>
      </div>
    );
  }
  if (state.phase === "no_course") {
    const displayTitle = state.title ?? title ?? "Сессия";
    return (
      <div className="pre-screen">
        <PreHeader title={displayTitle} eyebrow="Тренировка" />
        <p className="screen-message">Нет активного курса для этого экрана (или их больше одного).</p>
        <div className="pre-transport">
          <Button className="action-button vs-primary" size="l" stretched onClick={onGoToWorkout}>
            Перейти в обычную "Тренировку"
          </Button>
        </div>
      </div>
    );
  }

  const isStarting = state.phase === "starting";
  const step = state.phase === "ready_step" ? state : null;
  const generic = state.phase === "ready_generic" ? state : null;
  const manualReady = state.phase === "ready_manual" ? state : null;
  const planItemIds =
    step?.planItemIds ?? generic?.planItemIds ?? manualReady?.planItemIds
    ?? (state.phase === "starting" ? state.planItemIds : []);
  const programName = step?.programName ?? generic?.programName ?? manualReady?.title ?? null;
  const displayTitle = programName ?? title ?? (state.phase === "starting" ? state.title : undefined) ?? "Сессия";

  if (activeConflict !== null && !isStarting) {
    return (
      <div className="pre-screen" data-testid="active-session-conflict">
        <PreHeader title={displayTitle} eyebrow="Тренировка" />
        <p className="screen-message">
          Уже идёт другая тренировка{activeConflict.title ? ` — «${activeConflict.title}»` : ""}. Сначала продолжи или заверши её.
        </p>
        <div className="pre-transport">
          <Button className="action-button vs-primary" size="l" stretched onClick={() => onStarted(activeConflict)}>
            Продолжить текущую
          </Button>
          <Button className="action-button vs-plain" size="l" stretched mode="plain" onClick={onGoToWorkout}>
            Назад
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="pre-screen" data-testid="session-pre">
      <BackChevron testId="session-pre-back" onClick={onGoToWorkout} />
      <PreHeader title={displayTitle} />
      {summary !== null && (
        <>
          <p className="pre-meta" data-testid="session-pre-meta">{summary.meta}</p>
          <ul className="pre-exercises vs-rows" data-testid="session-pre-items">
            {summary.rows.map((row) => (
              <li key={row.id} className="pre-exercise">
                <span className="pre-exercise-name">{row.name}</span>
                <span className="pre-exercise-line">{row.line}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {step && (
        <>
          <BlockTargetCard index={1} block={step.blockA} />
          <BlockTargetCard index={2} block={step.blockB} />
        </>
      )}
      <div className="pre-transport">
        <Button
          className="action-button vs-primary" size="l" stretched disabled={isStarting}
          onClick={() => void handleStart(planItemIds, displayTitle)}
        >
          {isStarting ? <Spinner size="s" /> : "Начать"}
        </Button>
      </div>
    </div>
  );
}
