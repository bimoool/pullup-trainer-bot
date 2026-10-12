import { expect, test, type Page } from "@playwright/test";

import { answerChecksV2, noWakeLock, openPreScreen, playSetsV2 } from "../fixtures/builderFlow";
import { buildInitData, getTestBotToken } from "../fixtures/initData";
import { openAppAs } from "../fixtures/setup";

/** Ложный итог «Тренировка уже была завершена…» (ответ «Сохранить» вместо первого завершения). */
const FALSE_REPEAT = "Тренировка уже была завершена";

async function completedCard(page: Page, telegramId: number, sessionId: number) {
  const initData = buildInitData({ id: telegramId, firstName: "E2E" }, getTestBotToken());
  const response = await page.request.get("/api/v2/sessions?status=completed", { headers: { "X-Telegram-Init-Data": initData } });
  const cards = (await response.json()).sessions as { id: number; plan_item_id: number | null; status: string }[];
  return cards.filter((card) => card.id === sessionId);
}

// issue #305 × #306 — программа «Подтягивания» V5.6 на Live Engine v2.
// scripts/e2e_seed.py plan_week_start_session 930501: M = 12 → переходная неделя (A 5/5/5/5+, сила 5×5 масса тела).
// scripts/e2e_seed.py v5_one_rep_max 930502: тот же курс без E1RM — пред-экран просит 1RM.

test("V5.6 A: после последнего подхода — подтверждение техники и отдыха, затем одно завершение с прибавкой", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, 930_501);
  await openPreScreen(page, "Подтягивания");
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByText("Живая тренировка")).toBeVisible();

  // AMRAP: показана обязательная минимальная цель p4, а не «Максимум».
  await playSetsV2(page, ["5", "5", "5"]);
  await page.getByTestId("engine-skip").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл");
  await expect(page.getByTestId("engine-target")).toContainText("4/4 · Минимум 5 повт. (AMRAP)");
  await playSetsV2(page, ["7", "5", "5", "5", "5", "5"]);

  // Последний подход не завершает тренировку: движок ждёт ответов (CONFIRM), часы остановлены.
  await expect(page.getByTestId("engine-confirm")).toBeVisible();
  await expect(page.getByTestId("engine-complete")).toHaveCount(0);
  await expect(page.getByTestId("engine-checks-block-0")).toBeVisible();
  await expect(page.getByTestId("engine-checks-block-1")).toBeVisible();
  await answerChecksV2(page, "valid");
  const completion = page.waitForResponse((r) => r.url().includes("/events") && r.status() === 200);
  await page.getByTestId("engine-confirm-submit").click();
  const body = await (await completion).json();
  expect(body.status).toBe("completed");
  // Техника подтверждена, AMRAP 7 ≥ p4 + 2 → зелёный A: +1 обязательное повторение.
  expect(body.course_progression.blocks[0].decision).toBe("add_mandatory_rep");

  await expect(page.getByTestId("engine-complete")).toBeVisible();
  const saved = page.waitForResponse((r) => r.url().includes("/complete") && r.status() === 200);
  await page.getByTestId("engine-save").click();
  // «Сохранить» дописывает оценку и прогрессию повторно не считает — сервер так и отвечает.
  const save = await (await saved).json();
  expect(save.progression_skipped_reason).toBe("already_completed");
  expect(save.course_progression ?? null).toBeNull();

  // Summary — фактический итог первого (и единственного) завершения, без ложного «уже была завершена».
  await expect(page.getByTestId("course-progression")).toBeVisible();
  await expect(page.getByTestId("course-progression")).toContainText(`Следующая тренировка ${body.course_progression.next_workout_role}`);
  await expect(page.getByText(FALSE_REPEAT)).toHaveCount(0);
  const cards = await completedCard(page, 930_501, body.id);
  expect(cards).toHaveLength(1); // журнал — один раз
  expect(cards[0].plan_item_id).not.toBeNull(); // занятие плана засчитано

  expect(apiFailures).toEqual([]);
  expect(noWakeLock(consoleErrors)).toEqual([]);
});

test("V5.6 A: раннее завершение — итог «досрочно» (без прогрессии), история и кредит занятия есть", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, 930_503);
  await openPreScreen(page, "Подтягивания");
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  await playSetsV2(page, ["5", "5"]);

  const finished = page.waitForResponse((r) => r.url().includes("/events") && r.status() === 200
    && r.request().postDataJSON().events.some((e: { type: string }) => e.type === "finish_early"));
  const saved = page.waitForResponse((r) => r.url().includes("/complete") && r.status() === 200);
  await page.getByTestId("engine-finish").click();
  await page.getByTestId("engine-finish-confirm").click();
  const first = await (await finished).json();
  expect(first.status).toBe("completed");
  expect(first.progression_skipped_reason).toBe("abandoned"); // недоделка — прогрессия не считается (#307)
  expect(first.course_progression ?? null).toBeNull();
  expect((await (await saved).json()).progression_skipped_reason).toBe("already_completed");

  await expect(page.getByText("Прогрессия не пересчитана — сессия завершена досрочно.")).toBeVisible();
  await expect(page.getByText(FALSE_REPEAT)).toHaveCount(0);
  await expect(page.getByTestId("course-progression")).toHaveCount(0);
  const cards = await completedCard(page, 930_503, first.id);
  expect(cards).toHaveLength(1); // в истории
  expect(cards[0].plan_item_id).not.toBeNull(); // занятие плана засчитано (кредит), прогрессии нет

  expect(apiFailures).toEqual([]);
  expect(noWakeLock(consoleErrors)).toEqual([]);
});

test("V5.6: нет 1RM — тест проходится в приложении по лестнице, результат открывает тренировку", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, 930_502);
  await openPreScreen(page, "Подтягивания");
  await expect(page.getByTestId("course-setup-required")).toBeVisible();
  await expect(page.getByTestId("one-rm-test")).toBeVisible();

  await page.getByTestId("one-rm-start").click();
  await expect(page.getByTestId("one-rm-next")).toHaveText("Подход 1 из 8: собственный вес × 5");
  await page.getByTestId("one-rm-success").click();
  await expect(page.getByTestId("one-rm-next")).toHaveText("Подход 2 из 8: +7.5 кг × 3");
  await page.getByTestId("one-rm-success").click();
  await expect(page.getByTestId("one-rm-next")).toHaveText("Подход 3 из 8: +15 кг × 1");
  await page.getByTestId("one-rm-speed").getByRole("button", { name: "Получилось · Медленно" }).click();
  await expect(page.getByTestId("one-rm-next")).toHaveText("Подход 4 из 8: +16.25 кг × 1");
  // Стоп после первой неудачной/недействительной попытки; результат — последний успешный вес.
  await page.getByTestId("one-rm-fail").click();
  await expect(page.getByTestId("one-rm-finished")).toContainText("Тест окончен: 4 подх.");
  const saved = page.waitForResponse((r) => r.url().endsWith("/course/one-rep-max") && r.status() === 200);
  await page.getByTestId("one-rm-save").click();
  expect((await (await saved).json()).one_rep_max.e1rm_kg).toBe("15");

  // E1RM 15 при массе 75: 0,75·90 − 75 < 0 → сила с собственным весом; вход больше не нужен.
  await expect(page.getByText("Блок 2: 5×5 масса тела")).toBeVisible();
  await expect(page.getByRole("button", { name: "Начать", exact: true })).toBeEnabled();

  expect(apiFailures).toEqual([]);
  expect(noWakeLock(consoleErrors)).toEqual([]);
});
