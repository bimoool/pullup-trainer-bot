import { expect, test } from "@playwright/test";

import { runOwnerJourney } from "../fixtures/ownerJourney";
import { openAppAs } from "../fixtures/setup";

// Сквозной сценарий владельца в режиме Telegram (волна 3). Тело — fixtures/ownerJourney.ts. Сид: ux_editor_journey 941020.
test("сквозной сценарий: остановить старый план → создать новый → расписание → перезагрузка", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, 941_020);
  await runOwnerJourney(page);
  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
