import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py not_onboarded ничего не сидирует — статус
// "not_registered" (app/web/routes.py::get_hello) означает отсутствие
// строки users вообще, поэтому достаточно фиксированного telegram_id, под
// которым в этой CI-БД гарантированно никто не заведён.
const TELEGRAM_ID = 900_001;

test("совсем новый пользователь: сразу видит замер Mini App, без нижнего меню", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  // issue #124 (PR 2) заменил старый текст-заглушку "Онбординг ещё не
  // пройден. Начни его в боте." на полноценный экран OnboardingScreen —
  // onboarding_step="not_registered" стартует с того же первого вопроса
  // замера, что и "baseline" (POST /api/onboarding/baseline сам заводит
  // User). Раньше этот тест проверял старую заглушку — issue #126,
  // повторное падение CI после мержа PR 2 issue #124.
  await expect(page.getByLabel("Число подтягиваний")).toBeVisible();
  // Нижнее меню (и вкладка "Тренировка" внутри него) рендерится только при
  // onboarding_step="done" (см. App.tsx) — на этом статусе его не должно
  // быть вообще, не только на вкладке "Тренировка" по умолчанию.
  await expect(page.getByText("Тренировка", { exact: true })).toHaveCount(0);

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
