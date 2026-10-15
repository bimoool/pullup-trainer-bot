import { isCompleteDecimal } from "./decimalInput.ts";

/**
 * Правка подхода в отдыхе Live-движка v2 (аудит staging 6475bc0, H2). Пока открыт редактор, отдых может
 * закончиться: экран переходит в следующую фазу и закрывает редактор. Раньше введённое значение при этом
 * молча пропадало. Теперь черновик сохраняется событием `correct_previous` (движок принимает его в любой
 * фазе), если в нём полное число, отличное от записанного. Без DOM/React — tests/liveEditDraft.test.ts.
 */
export type EditTarget = {
  block_index: number;
  set_index: number;
  round_index: number | null;
  value: number | null;
};

export type CorrectionPayload = Omit<EditTarget, "value"> & { value: number };

/** Payload `correct_previous` для черновика правки или null (нечего сохранять: не число или без изменений). */
export function pendingCorrection(target: EditTarget | null, draft: string): CorrectionPayload | null {
  if (target === null || !isCompleteDecimal(draft)) {
    return null;
  }
  const value = Number(draft);
  if (!Number.isFinite(value) || value === target.value) {
    return null;
  }
  return { block_index: target.block_index, set_index: target.set_index, round_index: target.round_index, value };
}

/** Сообщение после автосохранения черновика при смене фазы. */
export function autosavedEditMessage(target: EditTarget, value: number): string {
  return `Подход ${target.set_index + 1} исправлен: ${value}`;
}
