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

async function onboardAndOpenSetup(page: Page, telegramId: number, theme: "light" | "dark" = "light") {
  await openAppAs(page, telegramId, { theme });
  await page.getByLabel("Сколько подтягиваний вышло?").fill("16");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByRole("button", { name: "Да" }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByLabel("Пол").selectOption({ label: "Мужской" });
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Дата рождения").fill("1992-04-15");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Часовой пояс").selectOption({ label: "Москва (UTC+3)" });
  // CI 9fbab6f: POST анкеты иногда дольше 5 с — ждём сам ответ, а не Главную по таймауту по умолчанию.
  const questionnaire = page.waitForResponse(
    (r) => r.url().includes("/api/onboarding/questionnaire") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Готово" }).click();
  expect((await questionnaire).ok()).toBe(true);
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();
  await page.getByRole("button", { name: /^Подтягивания/ }).first().click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await expect(page.getByRole("button", { name: "В плане" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
  await expect(page.getByTestId("course-setup-required")).toBeVisible();
  await expect(page.getByTestId("one-rm-start")).toBeVisible();
  // Mass is requested here, for this calculation, rather than during registration.
  await expect(page.getByTestId("course-input-body_mass_kg")).toBeVisible();
  await page.getByTestId("course-input-body_mass_kg").fill("80");
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
  await expect(error).toContainText("не хватает: ваш вес (масса тела), шаг дополнительного веса");
  await expect(error).not.toContainText("/api/");
});

/**
 * Первый вход, понятность формы (тот же staging-отзыв: в шаг веса вписали 16). Раньше: поля «Или: вы недавно
 * закрыли 5×5…» стояли ДО теста 1RM, альтернативой которому были, у шага веса не было примера, а что обязательно и
 * что делает «Сохранить» — не говорилось.
 */
test("форма входов: что обязательно, тест ИЛИ 5×5 / 5×3, шаг веса с примером рядом с тестом", async ({ page }) => {
  await onboardAndOpenSetup(page, freshId());
  const steps = page.getByTestId("course-setup-steps");
  await expect(steps).toContainText("ваш вес");
  await expect(steps).toContainText("шаг дополнительного веса");
  await expect(steps).toContainText("одно из двух: пройдите тест 1RM ниже — отдельным свежим днём");
  await expect(steps).toContainText("«Сохранить» записывает числа из полей");
  const data = page.getByTestId("course-setup-data");
  await expect(data).toContainText("Самый маленький диск или гантель");
  await expect(data).toContainText("обычно 1,25 или 2,5");
  await expect(data).toContainText("Это не ваш вес и не вес на поясе");
  await expect(data.getByTestId("course-input-known_strength_a_kg")).toHaveCount(0);
  const known = page.getByTestId("course-setup-known-strength");
  await expect(known).toContainText("Вариант 2: недавний 5×5 / 5×3 вместо теста");
  await expect(known).toContainText("закрыли 5×5 с +10 кг — впишите 10");
  await expect(page.getByTestId("one-rm-test")).toContainText("Вариант 1: тест 1RM в приложении");
  // Порядок на экране: шаг веса → тест 1RM → недавний 5×5 / 5×3.
  const top = async (testId: string) => (await page.getByTestId(testId).boundingBox())?.y ?? Number.NaN;
  const [stepY, testY, knownY] = [
    await top("course-input-load_step_kg"), await top("one-rm-test"), await top("course-setup-known-strength"),
  ];
  expect(stepY).toBeLessThan(testY);
  expect(testY).toBeLessThan(knownY);
});

test("«Сохранить» с нечисловым шагом: сервер 422 — текст для человека, не «PUT /api/… failed: 422»", async ({ page }) => {
  await onboardAndOpenSetup(page, freshId());
  const put = page.waitForResponse((r) => r.url().includes("/course/inputs") && r.request().method() === "PUT");
  await page.getByTestId("course-input-load_step_kg").fill("abc");
  await page.getByTestId("course-setup-save").click();
  expect((await put).status()).toBe(422);
  const error = page.getByTestId("course-setup-form").getByRole("alert");
  await expect(error).toContainText("Сервер не принял введённые данные — проверьте числа");
  await expect(error).toContainText("Код 422.");
  await expect(error).not.toContainText("/api/");
  await expect(error).not.toContainText("failed");
});

test("вариант 2: шаг веса + недавний 5×5 и «Сохранить» — форма закрывается, теста 1RM не нужно", async ({ page }) => {
  await onboardAndOpenSetup(page, freshId());
  await page.getByTestId("course-input-load_step_kg").fill("2,5");
  await page.getByTestId("course-input-known_strength_a_kg").fill("10");
  await page.getByTestId("course-setup-save").click();
  await expect(page.getByTestId("course-setup-required")).toHaveCount(0);
  await expect(page.getByTestId("one-rm-test")).toHaveCount(0);
  await expect(page.getByText(/^Блок 2: 5×5/)).toBeVisible();
});

// #359: long speed labels used the five-column effort grid and overlapped on narrow screens.
// Reach the single-rep step through actual onboarding and API ladder responses, without a seed or route mock.
for (const width of [320, 390]) {
  for (const theme of ["light", "dark"] as const) {
    test(`1RM: ${width}px ${theme} — подписи и области нажатия скорости не перекрываются`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 844 });
      await onboardAndOpenSetup(page, freshId(), theme);
      await page.getByTestId("course-input-load_step_kg").fill("2,5");
      await page.getByTestId("one-rm-start").click();
      await expect(page.getByTestId("one-rm-next")).toHaveText("Подход 1 из 8: собственный вес × 5");
      await page.getByTestId("one-rm-success").click();
      await expect(page.getByTestId("one-rm-next")).toHaveText("Подход 2 из 8: +7.5 кг × 3");
      await page.getByTestId("one-rm-success").click();
      await expect(page.getByTestId("one-rm-next")).toHaveText("Подход 3 из 8: +15 кг × 1");

      const speed = page.getByTestId("one-rm-speed");
      await speed.scrollIntoViewIfNeeded();
      const bounds = await speed.getByRole("button").evaluateAll((buttons) => buttons.map((button) => {
        const box = button.getBoundingClientRect();
        const text = document.createRange();
        text.selectNodeContents(button);
        return {
          label: button.textContent,
          box: box.toJSON() as { x: number; y: number; right: number; bottom: number; width: number; height: number },
          lines: Array.from(text.getClientRects(), (line) => ({ x: line.x, y: line.y, right: line.right, bottom: line.bottom })),
          ownsCenter: button.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)),
        };
      }));
      await testInfo.attach("speed-bounds", { body: JSON.stringify(bounds, null, 2), contentType: "application/json" });
      await testInfo.attach("speed-layout", { body: await page.screenshot(), contentType: "image/png" });
      expect(bounds.map(({ label }) => label)).toEqual([
        "Получилось · Быстро", "Получилось · Обычно", "Получилось · Медленно",
      ]);
      for (const { box, lines, ownsCenter } of bounds) {
        expect(box.width).toBeGreaterThanOrEqual(44);
        expect(box.height).toBeGreaterThanOrEqual(44);
        expect(ownsCenter).toBe(true);
        expect(lines.length).toBeGreaterThan(0);
        for (const line of lines) {
          expect(line.x).toBeGreaterThanOrEqual(box.x - 1);
          expect(line.right).toBeLessThanOrEqual(box.right + 1);
          expect(line.y).toBeGreaterThanOrEqual(box.y - 1);
          expect(line.bottom).toBeLessThanOrEqual(box.bottom + 1);
        }
      }
      for (let i = 0; i < bounds.length; i += 1) {
        for (const { box: other } of bounds.slice(i + 1)) {
          const { box } = bounds[i];
          expect(box.right <= other.x || other.right <= box.x || box.bottom <= other.y || other.bottom <= box.y).toBe(true);
        }
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

      // Every complete label remains a working target and submits its original speed value.
      for (const [index, choice] of [
        { label: "Быстро", value: "fast", nextKg: "22.5" },
        { label: "Обычно", value: "normal", nextKg: "25" },
        { label: "Медленно", value: "slow", nextKg: "27.5" },
      ].entries()) {
        const response = page.waitForResponse((r) => r.url().endsWith("/course/one-rep-max/next-set") && r.status() === 200);
        await speed.getByRole("button", { name: `Получилось · ${choice.label}`, exact: true }).click();
        const next = await response;
        expect(next.request().postDataJSON().attempts.at(-1).speed).toBe(choice.value);
        await expect(page.getByTestId("one-rm-next")).toHaveText(`Подход ${index + 4} из 8: +${choice.nextKg} кг × 1`);
      }
    });
  }
}
