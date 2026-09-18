import { Button, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchDashboardStatus, type DashboardBlockResponse, type DashboardStatusResponse } from "./apiV2";

type Props = {
  initDataRaw: string;
  /** Сам процесс тренировки (таймер/ввод/сохранение) в этой волне не
   * переписан (issue #167, п.2 задачи) — кнопки действий здесь переключают
   * вкладку обратно на проверенный старый "workout" (WorkoutScreen.tsx),
   * не реализуют свою логику записи заново. */
  onGoToWorkout: () => void;
};

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "not_ready"; status: string }
  | { phase: "ready"; data: DashboardStatusResponse };

// Статусы, которые эта волна не обрабатывает картой блоков — тот же принцип,
// что STATUS_MESSAGES в WorkoutScreen.tsx для старой схемы, набор статусов
// другой (см. app/web/schemas_v2_dashboard.py::DashboardStatusResponse).
const STATUS_MESSAGES: Record<string, string> = {
  not_migrated: "У этого аккаунта ещё нет активного курса в новой схеме (/api/v2) — перенос через бэкфилл-скрипт.",
  too_early: "Ещё рано для следующей тренировки — минимальный отдых между тренировками не прошёл.",
  gap_retest_required: "Был долгий перерыв — нужен повторный замер (в старой схеме доступно в боте/Тренировке).",
  multiple_active_inclusions: "У аккаунта больше одного активного курса — Dashboard пока не умеет их различать.",
};

const WORK_SETS_GROWTH_NOTICES: Record<string, string> = {
  stall: "Объём блока A подрос — несколько тренировок подряд без роста цели.",
  ceiling: "Объём блока A подрос — цель уже у потолка одного подхода.",
};

function BlockCard({ letter, block }: { letter: "A" | "Б"; block: DashboardBlockResponse }) {
  return (
    <Section className="block-section" header={`Блок ${letter} — цель ${block.target}`}>
      <div className="block-header">
        <div className="block-badge">{letter}</div>
        <p className="block-subtitle">
          {`${block.work_sets} рабочих ${block.work_sets === 1 ? "подход" : "подхода"}`}
          {" · "}
          {block.equipment.label}
        </p>
      </div>
      {block.equipment.needs_new_equipment && (
        <p className="gap-banner">Снаряд для этого блока будет пересмотрен на следующей тренировке.</p>
      )}
    </Section>
  );
}

/**
 * Экспериментальный экран (issue #167, волна 4) — читает статус курса через
 * /api/v2/dashboard/status (app/web/routes_v2_dashboard.py), а не через
 * старый /api/workout/plan (app/web/routes.py::_resolve_plan_context).
 * Read-only витрина: без форм ввода подхода, без живого таймера — сам
 * процесс тренировки остаётся на WorkoutScreen.tsx (см. onGoToWorkout выше).
 *
 * Данные читаются из ProgramInclusion.progression_state — это состояние
 * двигает вперёд ТОЛЬКО POST /api/v2/sessions, которого эта волна не
 * вызывает ниоткуда из реального UI (см. CLAUDE.md/issue #167): если
 * тренировки для этого аккаунта продолжают идти старым путём (бот/обычная
 * "Тренировка"), цифры здесь отражают состояние на момент последнего
 * бэкфилла/ручного вызова /api/v2/sessions, а не последнюю реальную
 * тренировку — известное ограничение волны 3, не баг этого экрана.
 */
export function DashboardScreen({ initDataRaw, onGoToWorkout }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await fetchDashboardStatus(initDataRaw);
        if (cancelled) {
          return;
        }
        setState(data.status === "ready" ? { phase: "ready", data } : { phase: "not_ready", status: data.status });
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

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю статус курса (v2)…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить: {state.message}</p>;
  }
  if (state.phase === "not_ready") {
    return (
      <div>
        <p className="plan-title">Dashboard (v2, эксперимент)</p>
        <p className="screen-message">
          {STATUS_MESSAGES[state.status] ?? `Статус пока не поддержан здесь: ${state.status}.`}
        </p>
        <Button className="action-button" size="l" stretched onClick={onGoToWorkout}>
          Перейти в обычную "Тренировку"
        </Button>
      </div>
    );
  }

  const { data } = state;
  return (
    <div>
      <p className="plan-title">Dashboard (v2, эксперимент)</p>
      <p className="screen-message">
        Курс: {data.program_name ?? "без названия"}. Данные — из новой многокурсовой схемы (/api/v2), могут отставать
        от последней реальной тренировки, пока она записывается обычным путём.
      </p>
      {data.is_gap_rollback && <p className="gap-banner">Был перерыв — цель блока A немного снижена, это нормально.</p>}
      {data.work_sets_growth_reason && (
        <p className="gap-banner">{WORK_SETS_GROWTH_NOTICES[data.work_sets_growth_reason]}</p>
      )}
      <p className="gap-banner">
        Тест на максимум блока A и чередование тяжёлой блока Б пока не поддержаны в Dashboard — см. обычный экран
        "Тренировка".
      </p>

      {data.block_a && <BlockCard letter="A" block={data.block_a} />}
      {data.block_b && <BlockCard letter="Б" block={data.block_b} />}

      <Button className="action-button" size="l" stretched onClick={onGoToWorkout}>
        Внести результат в обычной "Тренировке"
      </Button>
    </div>
  );
}
