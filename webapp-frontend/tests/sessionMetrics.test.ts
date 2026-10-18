import assert from "node:assert/strict";
import { test } from "node:test";

import { countExercises, formatSessionDuration } from "../src/sessionMetrics.ts";
import { journalCardStats } from "../src/journalStats.ts";

// UX-03: одна функция показа длительности. 0/null — «без длительности», никогда «0:00»/«0 мин».
test("formatSessionDuration: 30 с (активное время) -> «30 с», не «0:00»", () => {
  assert.equal(formatSessionDuration(30), "30 с");
});
test("formatSessionDuration: 40 с (досрочное завершение) -> «40 с»", () => {
  assert.equal(formatSessionDuration(40), "40 с");
});
test("formatSessionDuration: от минуты — «N мин» (1800 с = 30 мин, 90 с округляется до 2 мин)", () => {
  assert.equal(formatSessionDuration(1800), "30 мин");
  assert.equal(formatSessionDuration(90), "2 мин");
  assert.equal(formatSessionDuration(60), "1 мин");
});
test("formatSessionDuration: 0 и null — «без длительности»", () => {
  assert.equal(formatSessionDuration(0), "без длительности");
  assert.equal(formatSessionDuration(null), "без длительности");
  assert.equal(formatSessionDuration(undefined), "без длительности");
});

// UX-17: «Упражнений» — упражнения, не блоки. Курс: блоки «Объём (А)» и «Сила (Б)» — одно упражнение.
test("countExercises: два блока одного упражнения — 1; разные — 2; без id — по блоку", () => {
  const b = (exercise_id: number | null, complex_id: number | null = null) => ({ exercise_id, complex_id });
  assert.equal(countExercises([b(5), b(5)]), 1);
  assert.equal(countExercises([b(5), b(6)]), 2);
  assert.equal(countExercises([b(null), b(null)]), 2);
  assert.equal(countExercises([]), 0);
});

// UX-03: карточка Журнала у активности тоже не показывает «0:00».
test("journalCardStats: активность короче минуты — «30 с»", () => {
  const [duration] = journalCardStats({ blocks: [], effort: null, activity_type: "yoga", duration_seconds: 30 });
  assert.equal(duration.value, "30 с");
});

// UX-14: карточка по времени: подходы и суммарное время (30+25 = 55 с), без прочерков.
test("journalCardStats: подходы по времени (unit=s) — «Время 0:55»", () => {
  const log = (n: number, v: string) => ({ set_number: n, is_max_set: false, metric_type: "x", value: v, unit: "s", effort: null, note: null });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const stats = journalCardStats({ blocks: [{ order_index: 0, set_logs: [log(1, "30"), log(2, "25")], result: null, protocol_type: null }] as any, effort: null });
  assert.deepEqual(stats.map((s) => s.value), ["2", "0:55", "—"]);
});

// UX-17: в деталях видно, какая резина/вес использованы в блоке.
test("courseBlockEquipment: резина, без помощи, вес, нет данных", async () => {
  const { courseBlockEquipment } = await import("../src/sessionMetrics.ts");
  const snapshot = {
    provenance: {
      course_program: {
        blocks: [
          { assistance: { kind: "band", name: "Красная 15–35", colour: "красная", attachment: "петля" }, external_load_kg: null },
          { assistance: { kind: "bodyweight" }, external_load_kg: "0" },
          { assistance: { kind: "bodyweight" }, external_load_kg: "5.0" },
        ],
      },
    },
  };
  assert.equal(courseBlockEquipment(snapshot, 0), "Резина: Красная 15–35, красная, петля");
  assert.equal(courseBlockEquipment(snapshot, 1), "Без помощи");
  assert.equal(courseBlockEquipment(snapshot, 2), "Вес: +5 кг");
  assert.equal(courseBlockEquipment(snapshot, 3), null);
  assert.equal(courseBlockEquipment(null, 0), null);
});

// UX-04: занятие из аудита. Рабочие 53 повт./8 подходов + максимум 7 повт./1 попытка = Журнал «9 · 60».
test("repsSplit: 53/8 + 7/1 = 60/9; без подходов на максимум — null", async () => {
  const { repsSplit } = await import("../src/sessionMetrics.ts");
  const work = { protocol_type: "reps_sets", unit: "reps", total_reps: "53", set_count: 8, attempt_count: null };
  const max = { protocol_type: "max_effort", unit: "reps", total_reps: "7", set_count: null, attempt_count: 1 };
  assert.deepEqual(repsSplit([work, max]), { workReps: 53, workSets: 8, maxReps: 7, maxAttempts: 1, totalReps: 60, totalSets: 9 });
  assert.equal(repsSplit([work]), null);
  assert.equal(repsSplit([max]), null);
});
