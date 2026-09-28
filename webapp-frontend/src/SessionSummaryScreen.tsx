import { Button, Section } from "@telegram-apps/telegram-ui";

import type { LiveSessionCompleteResponse, SetLogResponseV2 } from "./apiV2";
import { formatDuration, formatIntervalsCount, formatNumber } from "./blockFormat";

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
  return (
    <div>
      {title && <p className="plan-title">{title}</p>}
      <p className="plan-title">Тренировка завершена</p>

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
        const status = isComplete ? "✅" : "▫️";
        const counter = intervalResult !== null || target === 0 ? "" : ` — ${done}/${target}`;
        const header = `${status}${name !== null ? ` ${name}` : ""}${counter}`;
        const best = isMax && done > 0 ? Math.max(...block.set_logs.map((log) => Number(log.value))) : null;
        return (
          <Section key={block.order_index} className="block-section" header={header}>
            {intervalResult !== null ? (
              <>
                <p className="block-subtitle">{formatDuration(intervalResult.actual_duration_seconds)} выполнено</p>
                {block.interval_config && (
                  <p className="block-subtitle">
                    {block.interval_config.work_seconds} сек работа / {block.interval_config.rest_seconds} сек отдых
                  </p>
                )}
                <p className="block-subtitle">{formatIntervalsCount(intervalResult.completed_cycles)}</p>
              </>
            ) : (
              <>
                {block.set_logs.map((log) => (
                  <p key={log.set_number} className="block-subtitle">
                    {isMax ? "Попытка" : "Подход"} {log.set_number}: {formatLogValue(log)}
                  </p>
                ))}
                {best !== null && <p className="block-subtitle">Лучший результат: {formatNumber(best)}</p>}
                {done === 0 && <p className="block-subtitle">Не выполнено — осталось в плане.</p>}
              </>
            )}
          </Section>
        );
      })}

      {result.progression_result && (
        <Section className="block-section" header="Новая цель">
          {result.blocks.length >= 1 && (() => {
            const name = result.blocks[0].exercise_id !== null && resolveExerciseName
              ? resolveExerciseName(result.blocks[0].exercise_id)
              : null;
            const { target_before, target_after } = result.progression_result.block_a;
            return (
              <p className="block-subtitle">
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
              <p className="block-subtitle">
                {name !== null && `${name}: `}{target_before} → {target_after}
              </p>
            );
          })()}
        </Section>
      )}
      {result.progression_skipped_reason && (
        <p className="gap-banner">
          {SKIPPED_REASON_LABELS[result.progression_skipped_reason] ?? result.progression_skipped_reason}
        </p>
      )}

      <Button className="action-button" size="l" stretched onClick={onClose}>
        Закрыть
      </Button>
    </div>
  );
}
