import { plural } from "./plural.ts";

/**
 * Строка подходов блока устаревшей STEP-программы на пред-экране и в Dashboard. Число подходов должно совпадать с
 * тем, что исполнит Live («Подход 1 / N») и посчитает Summary («done / N»): живой старт строит блок как
 * `work_sets` рабочих подходов + `max_sets` подходов на максимум (сервер: resolve_progression_block).
 * «3 рабочих подхода + подход на максимум · всего 4».
 */
export function stepBlockSetsLine(block: { work_sets: number; max_sets?: number | null }): string {
  const work = `${block.work_sets} ${plural(block.work_sets, "рабочий подход", "рабочих подхода", "рабочих подходов")}`;
  const max = block.max_sets ?? 0;
  if (max <= 0) {
    return work;
  }
  const maxPart = max === 1 ? "подход на максимум" : `${max} ${plural(max, "подход", "подхода", "подходов")} на максимум`;
  return `${work} + ${maxPart} · всего ${block.work_sets + max}`;
}
