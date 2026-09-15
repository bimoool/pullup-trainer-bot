import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py not_onboarded ничего не сидирует — статус
// "not_onboarded" (app/web/routes.py::get_hello) означает отсутствие
// строки users вообще, поэтому достаточно фиксированного telegram_id, под
// которым в этой CI-БД гарантированно никто не заведён.
const TELEGRAM_ID = 900_001;

test("совсем новый пользователь: приложение отправляет в бота, без нижнего меню", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  await expect(page.getByText("Онбординг ещё не пройден. Начни его в боте.")).toBeVisible();
  // Нижнее меню (и вкладка "Тренировка" внутри него) рендерится только при
  // is_onboarded=true (см. App.tsx) — на этом статусе его не должно быть
  // вообще, не только на вкладке "Тренировка" по умолчанию.
  await expect(page.getByText("Тренировка", { exact: true })).toHaveCount(0);

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
