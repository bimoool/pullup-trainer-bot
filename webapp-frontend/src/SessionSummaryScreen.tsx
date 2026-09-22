import { Button, Section } from "@telegram-apps/telegram-ui";

import type { LiveSessionCompleteResponse } from "./apiV2";

type Props = {
  result: LiveSessionCompleteResponse;
  onClose: () => void;
  /** Checkpoint 4B (issue #188) — тот же опциональный резолвер, что
   * SessionLiveScreen.tsx; SessionV2Lab.tsx не передаёт его, сохраняет
   * прежний фолбэк "Упражнение #id". */
  resolveExerciseName?: (exerciseId: number) => string;
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
export function SessionSummaryScreen({ result, onClose, resolveExerciseName }: Props) {
  return (
    <div>
      <p className="plan-title">Тренировка завершена</p>

      {result.blocks.map((block) => {
        const target = block.targets.length;
        const done = block.set_logs.length;
        const isComplete = target > 0 && done >= target;
        const name =
          block.exercise_id !== null && resolveExerciseName
            ? resolveExerciseName(block.exercise_id)
            : `Упражнение #${block.exercise_id ?? block.complex_id}`;
        return (
          <Section
            key={block.order_index}
            className="block-section"
            header={`${isComplete ? "✅" : "▫️"} ${name} — ${done}/${target}`}
          >
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
          {result.blocks.length >= 1 && (
            <p className="block-subtitle">
              {result.blocks[0].exercise_id !== null && resolveExerciseName
                ? resolveExerciseName(result.blocks[0].exercise_id)
                : "Первое упражнение"}:{" "}
              {result.progression_result.block_a.target_before} → {result.progression_result.block_a.target_after}
            </p>
          )}
          {result.blocks.length >= 2 && (
            <p className="block-subtitle">
              {result.blocks[1].exercise_id !== null && resolveExerciseName
                ? resolveExerciseName(result.blocks[1].exercise_id)
                : "Второе упражнение"}:{" "}
              {result.progression_result.block_b.target_before} → {result.progression_result.block_b.target_after}
            </p>
          )}
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
