import assert from "node:assert/strict";
import { test } from "node:test";

import { latestDelta, measuredAtFromDate, toDateInput, trendPoints } from "../src/bodyMetrics.ts";

test("toDateInput: локальная дата с нулями", () => {
  assert.equal(toDateInput(new Date(2026, 0, 5, 23, 59)), "2026-01-05");
});

test("measuredAtFromDate: сегодня — now, другой день — полдень, та же дата при правке — время сохраняется", () => {
  const now = new Date(2026, 9, 2, 8, 30);
  assert.equal(measuredAtFromDate("2026-10-02", now), now.toISOString());
  assert.equal(measuredAtFromDate("2026-09-20", now), new Date(2026, 8, 20, 12).toISOString());
  const existing = new Date(2026, 8, 20, 7, 15).toISOString();
  assert.equal(measuredAtFromDate("2026-09-20", now, existing), existing);
  assert.equal(measuredAtFromDate("2026-09-21", now, existing), new Date(2026, 8, 21, 12).toISOString());
});

test("trendPoints: порядок по времени, большее значение выше, пустой и одиночный случаи", () => {
  assert.deepEqual(trendPoints([], 300, 120), []);
  const single = trendPoints([{ value: "80", measured_at: "2026-09-01T10:00:00Z" }], 300, 120);
  assert.deepEqual(single, [{ x: 150, y: 60 }]);

  const points = trendPoints(
    [
      { value: "78", measured_at: "2026-09-10T10:00:00Z" },
      { value: "82", measured_at: "2026-09-01T10:00:00Z" },
      { value: "80", measured_at: "2026-09-05T10:00:00Z" },
    ],
    300,
    120,
    10,
  );
  assert.equal(points.length, 3);
  assert.deepEqual(points[0], { x: 10, y: 10 }); // самый ранний и самый тяжёлый — слева сверху
  assert.deepEqual(points[2], { x: 290, y: 110 }); // самый поздний и лёгкий — справа снизу
  assert.ok(points[0].x < points[1].x && points[1].x < points[2].x);
});

test("latestDelta: разница двух последних, null при одном замере", () => {
  assert.equal(latestDelta([{ value: "80", measured_at: "2026-09-01T10:00:00Z" }]), null);
  assert.equal(
    latestDelta([
      { value: "79.5", measured_at: "2026-09-10T10:00:00Z" },
      { value: "80.2", measured_at: "2026-09-01T10:00:00Z" },
    ]),
    -0.7,
  );
});
