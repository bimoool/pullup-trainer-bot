import { expect, test, type Page } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

/**
 * Первый обычный пользователь застрял в настройке курса (staging): «Начать тест» 1RM →
 * POST …/course/one-rep-max/next-set → 409, на экране только технический адрес.
 * Причина: «Начать тест» не отправлял заполненную форму — сервер проверял СОХРАНЁННЫЕ входы, шага веса там не было →
 * 409 {code: "course_setup_required", missing: ["load_step"]}; у этого ответа нет message, и клиент показывал
 * «POST /api/… failed: 409». Правила допуска и 48 ч не меняются.
 * Свежий обычный профиль (id вне ADMIN_IDS, без сидов пользователя): M = 16 → сила с весом → нужен тест 1RM.
 */
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
test.setTimeout(120_000);

const freshId = () => 7_600_000 + Math.floor(Math.random() * 90_000);

async function onboardAndOpenSetup(page: Page, telegramId: number) {
  await openAppAs(page, telegramId);
  await page.getByLabel("Сколько подтягиваний вышло?").fill("16");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByRole("button", { name: "Да" }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByLabel("Твой вес в кг?").fill("80");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Рост в см?").fill("180");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Пол").selectOption({ label: "Мужской" });
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Дата рождения").fill("1992-04-15");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Часовой пояс").selectOption({ label: "Москва (UTC+3)" });
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();
  await page.getByRole("button", { name: /^Подтягивания/ }).first().click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await expect(page.getByRole("button", { name: "В плане" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
  await expect(page.getByTestId("course-setup-required")).toBeVisible();
  await expect(page.getByTestId("one-rm-start")).toBeVisible();
}

function trackNextSet(page: Page) {
  const responses: { status: number; body: string }[] = [];
  page.on("response", async (response) => {
    if (response.url().includes("/one-rep-max/next-set")) {
      responses.push({ status: response.status(), body: await response.text() });
    }
  });
  return responses;
}

test("шаг веса введён, «Сохранить» не нажат — «Начать тест» сохраняет введённое и начинает лестницу", async ({ page }) => {
  await onboardAndOpenSetup(page, freshId());
  const nextSet = trackNextSet(page);
  await page.getByTestId("course-input-load_step_kg").fill("2,5");
  await page.getByTestId("one-rm-start").click();

  await expect.poll(() => nextSet.length).toBe(1);
  console.log(`next-set → ${JSON.stringify(nextSet)} · экран: ${await page.getByTestId("one-rm-test").innerText()}`);
  await expect(page.getByTestId("one-rm-next")).toHaveText("Подход 1 из 8: собственный вес × 5");
  await expect(page.getByTestId("one-rm-error")).toHaveCount(0);
  expect(nextSet.map((r) => r.status)).toEqual([200]);
});

test("шаг веса не указан — понятная причина и поле, а не технический адрес; правило не ослаблено", async ({ page }) => {
  await onboardAndOpenSetup(page, freshId());
  const nextSet = trackNextSet(page);
  await page.getByTestId("one-rm-start").click();

  const error = page.getByTestId("one-rm-error");
  await expect(error).toContainText("Чтобы начать тест, не хватает: шаг дополнительного веса");
  await expect(error).not.toContainText("/api/");
  await expect(error).not.toContainText("409");
  // Запрос не уходит, пока шага нет (сервер его всё равно не принял бы), лестница не начинается.
  expect(nextSet).toEqual([]);
  await expect(page.getByTestId("one-rm-next")).toHaveCount(0);
  await expect(page.getByTestId("course-input-load_step_kg")).toBeFocused();
});

test("шаг 16 кг: предупреждение, что прибавлять вес программа не сможет (0,5–2,5 кг), и что это не масса тела", async ({ page }) => {
  await onboardAndOpenSetup(page, freshId());
  await page.getByTestId("course-input-load_step_kg").fill("16");
  const warning = page.getByTestId("course-load-step-warning");
  await expect(warning).toContainText("больше 2,5 кг");
  await expect(warning).toContainText("не масса тела");
  await page.getByTestId("course-input-load_step_kg").fill("1,25");
  await expect(warning).toHaveCount(0);
});

test("сервер ответил course_setup_required — показан список недостающего по-русски, не адрес", async ({ page }) => {
  await onboardAndOpenSetup(page, freshId());
  await page.route("**/one-rep-max/next-set", (route) => route.fulfill({
    status: 409, contentType: "application/json",
    body: JSON.stringify({ detail: { code: "course_setup_required", missing: ["body_mass", "load_step"] } }),
  }));
  await page.getByTestId("course-input-load_step_kg").fill("2,5");
  await page.getByTestId("one-rm-start").click();
  const error = page.getByTestId("one-rm-error");
  await expect(error).toContainText("не хватает: масса тела, шаг дополнительного веса");
  await expect(error).not.toContainText("/api/");
});
