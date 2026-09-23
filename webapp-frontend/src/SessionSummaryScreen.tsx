import { Button, Section } from "@telegram-apps/telegram-ui";

import type { LiveSessionCompleteResponse } from "./apiV2";

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
function formatMinutesSeconds(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

type IntervalResult = {
  type: "interval";
  planned_duration_seconds: number;
  actual_duration_seconds: number;
  completed_cycles: number;
};

function isIntervalResult(value: unknown): value is IntervalResult {
  return typeof value === "object" && value !== null && (value as { type?: unknown }).type === "interval";
}

export function SessionSummaryScreen({ result, onClose, resolveExerciseName, title }: Props) {
  // Phase B2 (issue #215, раздел 17) — interval получает отдельную
  // rendering-ветку: не SetLog rows, не fake targets, не Упражнение #id.
  // Источник данных — уже полученный result.blocks[].result (сам result
  // на бэкенде читает TrainingSession.workout_snapshot + SessionBlock.result,
  // не live Complex definition — Summary здесь просто отображает то, что
  // уже пришло, никакого отдельного запроса).
  const intervalResult = result.blocks.length > 0 && isIntervalResult(result.blocks[0].result)
    ? result.blocks[0].result
    : null;

  if (intervalResult !== null) {
    return (
      <div>
        {title && <p className="plan-title">{title}</p>}
        <p className="plan-title">Тренировка завершена</p>
        <Section className="block-section">
          <p className="block-subtitle">{formatMinutesSeconds(intervalResult.actual_duration_seconds)} выполнено</p>
          {result.interval && (
            <p className="block-subtitle">
              {result.interval.work_seconds} сек работа / {result.interval.rest_seconds} сек отдых
            </p>
          )}
          <p className="block-subtitle">{intervalResult.completed_cycles} рабочих интервалов</p>
        </Section>
        <Button className="action-button" size="l" stretched onClick={onClose}>
          Закрыть
        </Button>
      </div>
    );
  }

  return (
    <div>
      {title && <p className="plan-title">{title}</p>}
      <p className="plan-title">Тренировка завершена</p>

      {result.blocks.map((block) => {
        const target = block.targets.length;
        const done = block.set_logs.length;
        const isComplete = target > 0 && done >= target;
        // Integration fix (H2 hardening) — name=null (internal STEP-роль
        // без публичного имени, Checkpoint 3C) значит заголовок секции не
        // несёт имени вовсе, только статус/счёт — не "Блок A", не
        // "Упражнение #id", не выдуманный термин (раздел 5/8 задачи).
        // complex_id-путь (Комплекс) не тронут — вне scope этого фикса.
        const name = block.exercise_id !== null && resolveExerciseName
          ? resolveExerciseName(block.exercise_id)
          : (block.complex_id !== null ? "Комплекс" : null);
        const header = name !== null
          ? `${isComplete ? "✅" : "▫️"} ${name} — ${done}/${target}`
          : `${isComplete ? "✅" : "▫️"} ${done}/${target}`;
        return (
          <Section key={block.order_index} className="block-section" header={header}>
            {block.set_logs.map((log) => (
              <p key={log.set_number} className="block-subtitle">
                Подход {log.set_number}: {log.value} {log.unit}
              </p>
            ))}
            {done === 0 && <p className="block-subtitle">Не выполнено — осталось в плане.</p>}
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
