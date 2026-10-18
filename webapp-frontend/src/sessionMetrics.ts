/** Общие показатели занятия для Итога, деталей, Журнала и Аналитики (UX-03/04/17).
 * Длительность занятия — активное время движка, паузы не входят (решено); 0/нет значения — «без длительности». */

export const NO_DURATION_LABEL = "без длительности";

/** ЕДИНСТВЕННЫЙ показ длительности занятия: от минуты — «N мин», короче — «N с», 0/нет — «без длительности».
 * Аналитика считает минуты по тому же duration_seconds (round(Σ секунд / 60)), поэтому и здесь минуты округляются. */
export function formatSessionDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds <= 0) {
    return NO_DURATION_LABEL;
  }
  const whole = Math.round(seconds);
  if (whole < 60) {
    return whole > 0 ? `${whole} с` : NO_DURATION_LABEL;
  }
  return `${Math.round(whole / 60)} мин`;
}

/** Секунды активной работы движка (мс -> с) ровно по правилу сервера: (мс + 500) // 1000. */
export function activeSecondsFromMs(activeMs: number): number {
  return Math.floor((Math.max(0, activeMs) + 500) / 1000);
}

interface BlockIdentity {
  exercise_id: number | null;
  complex_id?: number | null;
}

/** Сколько УПРАЖНЕНИЙ в занятии (не блоков): блоки одного упражнения (курс: «Объём (А)» и «Сила (Б)») — одно.
 * Блок без идентичности (шаг/комплекс без id) считается сам за себя. */
export function countExercises(blocks: BlockIdentity[]): number {
  const identities = new Set<string>();
  let anonymous = 0;
  for (const block of blocks) {
    if (block.exercise_id !== null && block.exercise_id !== undefined) {
      identities.add(`e${block.exercise_id}`);
    } else if (block.complex_id !== null && block.complex_id !== undefined) {
      identities.add(`c${block.complex_id}`);
    } else {
      anonymous += 1;
    }
  }
  return identities.size + anonymous;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/** UX-17. Что использовано в блоке основного занятия — из замороженного рецепта сессии
 * (`provenance.course_program.blocks[i]`): резина («Резина: Красная, петля к перекладине»),
 * «Без помощи», дополнительный вес («Вес: +5 кг»). null — рецепта/данных нет, строку не выдумываем. */
export function courseBlockEquipment(snapshot: Record<string, unknown> | null | undefined, blockIndex: number): string | null {
  const program = asRecord(asRecord(asRecord(snapshot)?.["provenance"])?.["course_program"]);
  const blocks = program?.["blocks"];
  const block = Array.isArray(blocks) ? asRecord(blocks[blockIndex]) : null;
  if (block === null) {
    return null;
  }
  const load = Number(block["external_load_kg"]);
  if (block["external_load_kg"] !== null && block["external_load_kg"] !== undefined && Number.isFinite(load) && load > 0) {
    return `Вес: +${load} кг`;
  }
  const assistance = asRecord(block["assistance"]);
  if (assistance === null) {
    return null;
  }
  if (assistance["kind"] === "band") {
    const parts = ["name", "colour", "attachment"]
      .map((key) => assistance[key])
      .filter((part): part is string => typeof part === "string" && part.trim() !== "")
      .map((part) => part.trim());
    return parts.length > 0 ? `Резина: ${parts.join(", ")}` : "Резина";
  }
  return assistance["kind"] === "bodyweight" ? "Без помощи" : null;
}

interface PanelTotals {
  protocol_type: string;
  unit: string | null;
  total_reps: string | null;
  set_count: number | null;
  attempt_count: number | null;
}

export interface RepsSplit {
  workReps: number;
  workSets: number;
  maxReps: number;
  maxAttempts: number;
  totalReps: number;
  totalSets: number;
}

/** UX-04. «Всего повторений» панели рабочих подходов не включает подходы на максимум (они — отдельная панель),
 * а карточка Журнала считает всё вместе. Эта сводка склеивает обе части одного упражнения: рабочие + на максимум = то,
 * что видно в Журнале. null — у упражнения нет подходов на максимум в повторениях (делить нечего). */
export function repsSplit(panels: PanelTotals[]): RepsSplit | null {
  const work = panels.find((panel) => panel.protocol_type === "reps_sets");
  const max = panels.find((panel) => panel.protocol_type === "max_effort" && panel.unit === "reps");
  if (work === undefined || max === undefined || max.total_reps === null || !(Number(max.attempt_count) > 0)) {
    return null;
  }
  const workReps = Number(work.total_reps ?? 0);
  const workSets = work.set_count ?? 0;
  const maxReps = Number(max.total_reps);
  const maxAttempts = max.attempt_count ?? 0;
  return { workReps, workSets, maxReps, maxAttempts, totalReps: workReps + maxReps, totalSets: workSets + maxAttempts };
}
