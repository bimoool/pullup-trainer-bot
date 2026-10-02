import { Button } from "@telegram-apps/telegram-ui";

import type { LiveSessionCompleteResponse, SetLogResponseV2 } from "./apiV2";
import { formatDuration, formatIntervalsCount, formatNumber } from "./blockFormat";
import { Icon } from "./Icon";

type Props = {
  result: LiveSessionCompleteResponse;
  onClose: () => void;
  /** Заголовок тренировки верхнего уровня ("Подтягивания"/"Планка") — тот
   * же title, что PlanSessionFlow уже передаёт в SessionPreScreen
   * (Checkpoint 4A/4B, H2-A). Опционален — SessionV2Lab.tsx не передаёт
   * его, фолбэк на прежний общий заголовок остаётся тем же. */
  title?: string;
  /** Checkpoint 4B (issue #188) — тот же опциональный резолвер, что
   * SessionLiveScreen.tsx; SessionV2Lab.tsx не передаёт его, старое
   * поведение (SessionV2Lab использует не этот компонент напрямую с этим
   * пропом, а фолбэк ниже) не меняется.
   *
   * Integration fix (H2 hardening, issue #188) — возвращает `string | null`,
   * не молчаливый technical fallback: для internal STEP-ролей (block_a/
   * block_b, exercise.subcategory) Checkpoint 3C намеренно исключает их
   * из GET /exercises (чтобы их нельзя было выбрать в Add Exercise picker
   * вручную) — раньше резолвер сам подставлял "Упражнение #id" для них,
   * и этот фолбэк был неотличим от "имени действительно нет", из-за чего
   * секции ниже не могли решить, показывать ли name вообще. Теперь null
   * прямо значит "человекочитаемого имени для этого exercise_id нет" —
   * секции сами решают, что делать (не показывать label вовсе), не
   * дальше не пытаются угадать имя по id. */
  resolveExerciseName?: (exerciseId: number) => string | null;
};

const SKIPPED_REASON_LABELS: Record<string, string> = {
  abandoned: "Прогрессия не пересчитана — сессия завершена досрочно.",
  no_program_inclusion: "Прогрессия не пересчитана — нет активного курса со ступенчатой стратегией для этих упражнений.",
  blocks_do_not_match_step_roles: "Прогрессия не пересчитана — выполненные блоки не совпали с ролями блок A/Б курса.",
  already_completed: "Тренировка уже была завершена — прогрессия учтена при первом завершении.",
};

/**
 * Итог сессии (issue #185, раздел 10.9 docs/plan-and-specs.md). "Монеты"/
 * "новое достижение"/стрик из раздела 10.9 сюда НЕ добавлены — ни
 * app/services/live_session.py, ни app/services/session_log.py (тот же
 * путь для одноразовой записи волны 3) не вызывают GamificationService
 * вообще (проверено: `grep -rn Gamification app/services/session_log.py
 * app/services/live_session.py` пусто) — это открытый пробел бэкенда волны
 * 3, унаследованный сюда, а не забытая фронтенд-доработка; рисовать
 * "+N монет" без реального начисления значило бы врать пользователю.
 */
type IntervalResult = {
  type: "interval";
  planned_duration_seconds: number;
  actual_duration_seconds: number;
  completed_cycles: number;
};

function isIntervalResult(value: unknown): value is IntervalResult {
  return typeof value === "object" && value !== null && (value as { type?: unknown }).type === "interval";
}

/** Значение одного подхода без технических хвостов ("8.00 reps"). */
function formatLogValue(log: SetLogResponseV2): string {
  if (log.unit === "s") {
    return formatDuration(Number(log.value));
  }
  if (log.unit === "reps") {
    return `${formatNumber(log.value)} повт.`;
  }
  return `${formatNumber(log.value)} ${log.unit}`;
}

export function SessionSummaryScreen({ result, onClose, resolveExerciseName, title }: Props) {
  // R1 (инвариант J): каждый блок рендерится НЕЗАВИСИМО — interval в любой
  // позиции, рядом с reps/time/max. Ни один блок не определяет вид всей
  // сессии. Данные — то, что уже пришло в result (идентичность протокола из
  // замороженного снимка), отдельных запросов нет.
  const totalDone = result.blocks.reduce(
    (sum, block) => sum + (isIntervalResult(block.result) ? block.result.completed_cycles : block.set_logs.length), 0,
  );
  const hasInterval = result.blocks.some((block) => isIntervalResult(block.result));
  return (
    <div className="live-screen live-summary-screen">
      <div className="live-hero-done">
        <span className="live-check" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
        </span>
        <p className="live-done-title">Тренировка завершена</p>
        {title && <p className="live-workout-title">{title}</p>}
        <div className="live-stats">
          <div className="live-stat">
            <span className="live-stat-value">{totalDone}</span>
            <span className="live-stat-label">{hasInterval ? "Подходов и циклов" : "Подходов"}</span>
          </div>
          <div className="live-stat">
            <span className="live-stat-value">{result.blocks.length}</span>
            <span className="live-stat-label">{result.blocks.length === 1 ? "Упражнение" : "Упражнений"}</span>
          </div>
        </div>
      </div>

      {result.blocks.map((block) => {
        // name=null (internal STEP-роль без публичного имени) значит заголовок
        // несёт только статус/счёт — не "Блок A", не "Упражнение #id".
        const name = block.exercise_name !== null
          ? block.exercise_name
          : block.exercise_id !== null && resolveExerciseName
            ? resolveExerciseName(block.exercise_id)
            : (block.complex_id !== null ? "Комплекс" : null);
        const target = block.targets.length;
        const done = block.set_logs.length;
        const intervalResult = isIntervalResult(block.result) ? block.result : null;
        const isMax = block.protocol_type === "max_effort";
        const isComplete = intervalResult !== null || (target > 0 && done >= target);
        const counter = intervalResult !== null || target === 0 ? "" : ` — ${done}/${target}`;
        const header = `${name ?? ""}${counter}`.trim();
        const best = isMax && done > 0 ? Math.max(...block.set_logs.map((log) => Number(log.value))) : null;
        return (
          <section key={block.order_index} className="live-card">
            <h3 className="live-card-title">
              <Icon name={isComplete ? "checkCircle" : "circle"} size={18} className={isComplete ? "vp-icon-lead vp-icon-done" : "vp-icon-lead vp-icon-pending"} />
              {header}
              <span className="vp-sr-only">{header === "" ? "" : ", "}{isComplete ? "выполнено" : "не выполнено"}</span>
            </h3>
            {intervalResult !== null ? (
              <>
                <p className="live-row">{formatDuration(intervalResult.actual_duration_seconds)} выполнено</p>
                {block.interval_config && (
                  <p className="live-row">
                    {block.interval_config.work_seconds} сек работа / {block.interval_config.rest_seconds} сек отдых
                  </p>
                )}
                <p className="live-row">{formatIntervalsCount(intervalResult.completed_cycles)}</p>
              </>
            ) : (
              <>
                {block.set_logs.map((log) => (
                  <p key={log.set_number} className="live-row">
                    {isMax ? "Попытка" : "Подход"} {log.set_number}: {formatLogValue(log)}
                  </p>
                ))}
                {best !== null && <p className="live-row live-row-best">Лучший результат: {formatNumber(best)}</p>}
                {done === 0 && <p className="live-row">Не выполнено — осталось в плане.</p>}
              </>
            )}
          </section>
        );
      })}

      {result.progression_result && (
        <section className="live-card live-card-goal">
          <h3 className="live-card-title">Новая цель</h3>
          {result.blocks.length >= 1 && (() => {
            const name = result.blocks[0].exercise_id !== null && resolveExerciseName
              ? resolveExerciseName(result.blocks[0].exercise_id)
              : null;
            const { target_before, target_after } = result.progression_result.block_a;
            return (
              <p className="live-row">
                {name !== null && `${name}: `}{target_before} → {target_after}
              </p>
            );
          })()}
          {result.blocks.length >= 2 && (() => {
            const name = result.blocks[1].exercise_id !== null && resolveExerciseName
              ? resolveExerciseName(result.blocks[1].exercise_id)
              : null;
            const { target_before, target_after } = result.progression_result.block_b;
            return (
              <p className="live-row">
                {name !== null && `${name}: `}{target_before} → {target_after}
              </p>
            );
          })()}
        </section>
      )}
      {result.progression_skipped_reason && (
        <p className="gap-banner">
          {SKIPPED_REASON_LABELS[result.progression_skipped_reason] ?? result.progression_skipped_reason}
        </p>
      )}

      <div className="live-transport">
        <Button className="live-primary" size="l" stretched onClick={onClose}>
          Закрыть
        </Button>
      </div>
    </div>
  );
}
