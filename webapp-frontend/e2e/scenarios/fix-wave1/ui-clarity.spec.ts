import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { finishV2, noWakeLock, openPreScreen, playSetsV2 } from "../../fixtures/builderFlow";
import { openJournalEntry } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

/**
 * UI clarity (аудит пользователя): видимые подписи полей, человеческие подписи каталога, карточка курса V5.6,
 * объяснение помощи/веса, названия блоков в Журнале.
 *
 *  1. Онбординг и CourseSetupForm: подпись поля — видимый `<label>`, который переносится и не обрезается
 *     (раньше — `header` tgui: однострочный ellipsis; «…закрыли 5×5 (сила A)…» терялось). Матрица платформ
 *     Telegram ios / android / base (tdesktop) × 320/390 px × светлая/тёмная тема; пользователь на сочетание — новый.
 *  2. Каталог: «Подтягивания», не pull_ups/PULL_UPS; карточка курса — 2 основных занятия в неделю, без «10 × 3».
 *  3. Журнал: названия блоков объём/сила из снимка сессии — в деталях и в редакторе.
 *  4. Помощь/вес после замера: форма входов курса объясняет, зачем резина/вес — по существующим правилам допуска
 *     (CourseSetupForm «Зачем это нужно»; без выдуманных резины и килограммов). Экран «Снаряд для первой
 *     тренировки» (EquipmentPlanScreen) достижим только из админской «Dashboard»-лаборатории — в этот набор не входит.
 *
 * Скриншоты — в UIC_EVIDENCE_DIR (по умолчанию /tmp/uic_evidence).
 */

const EVIDENCE = process.env.UIC_EVIDENCE_DIR ?? "/tmp/uic_evidence";
mkdirSync(EVIDENCE, { recursive: true });
const shot = (page: Page, name: string) => page.screenshot({ path: resolve(EVIDENCE, `${name}.png`), fullPage: true });

const PLATFORMS = [
  { name: "ios", platform: "ios" },
  { name: "android", platform: "android" },
  { name: "base", platform: "tdesktop" },
] as const;
const WIDTHS = [320, 390] as const;
const THEMES: TelegramTheme[] = ["light", "dark"];

/** Посев v5_one_rep_max (только чтение), зарегистрирован в scripts/e2e_seed_all.sh. */
const ONE_RM_USER = 930_701;

// Случайные id (кратные 10): база от секунд загрузки модуля совпадала у воркеров, загрузившихся в одну секунду, —
// «новый» пользователь оказывался уже онбординговым (ретрай в CI 38863710119: нет «Сколько подтягиваний вышло?»).
const nextId = () => 7_300_000 + 10 * Math.floor(Math.random() * 60_000);

/** Подпись видима целиком: внутри окна, не обрезана ellipsis/overflow, связана с полем. */
async function expectCaption(page: Page, text: string, control?: "input" | "select", scope?: string) {
  const root = scope !== undefined ? page.getByTestId(scope) : page;
  const caption = root.locator("label.labeled-field-caption", { hasText: text });
  await expect(caption, `подпись «${text}»`).toBeVisible();
  const view = await caption.evaluate((el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return {
      text: el.textContent ?? "",
      inside: rect.left >= 0 && rect.right <= window.innerWidth + 0.5,
      clippedX: el.scrollWidth > el.clientWidth + 1,
      ellipsis: style.textOverflow === "ellipsis" || style.overflow === "hidden",
      lineHeight: parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.3,
      height: rect.height,
    };
  });
  expect(view.text.trim(), `текст подписи «${text}» целиком`).toContain(text);
  expect(view.inside, `«${text}» внутри окна`).toBe(true);
  expect(view.clippedX, `«${text}» не обрезана по ширине`).toBe(false);
  expect(view.ellipsis, `«${text}» без ellipsis/hidden`).toBe(false);
  expect(view.height, `«${text}» не пустая`).toBeGreaterThan(view.lineHeight * 0.9);
  if (control !== undefined) {
    // подпись — accessible name поля (htmlFor), а не aria-label/placeholder
    await expect(page.getByLabel(text, { exact: false }).locator("visible=true").first()).toBeVisible();
    expect(await page.locator(control).evaluateAll((els) => els.filter((e) => e.getAttribute("aria-label")).length)).toBe(0);
  }
}

async function fillOnboarding(page: Page, tag: string, labels: { baseline: boolean }) {
  if (labels.baseline) {
    await expectCaption(page, "Сколько подтягиваний вышло?", "input");
    await shot(page, `${tag}-onb-1-baseline`);
    await page.getByLabel("Сколько подтягиваний вышло?").fill("8");
    await page.getByRole("button", { name: "Далее" }).click();
    await page.getByRole("button", { name: "Да" }).click();
    // сразу после замера — что он значит для помощи/веса и следующий шаг (обычный пользователь, не admin)
    const qualification = page.getByTestId("baseline-qualification");
    await expect(qualification).toBeVisible();
    await expect(qualification).toContainText("начнётся с помощью");
    await expect(page.getByTestId("baseline-next-step")).toContainText("«Добавить в план»");
    await shot(page, `${tag}-onb-1b-after-baseline`);
    await page.getByRole("button", { name: "Продолжить" }).click();
  }
  await expectCaption(page, "Твой вес в кг?", "input");
  await shot(page, `${tag}-onb-2-weight`);
  await page.getByLabel("Твой вес в кг?").fill("78");
  await page.getByRole("button", { name: "Далее" }).click();
  await expectCaption(page, "Рост в см?", "input");
  await page.getByLabel("Рост в см?").fill("180");
  await page.getByRole("button", { name: "Далее" }).click();
  await expectCaption(page, "Пол?", "select");
  await page.getByLabel("Пол").selectOption({ label: "Мужской" });
  await page.getByRole("button", { name: "Далее" }).click();
  await expectCaption(page, "Дата рождения?", "input");
  await page.getByLabel("Дата рождения").fill("1992-04-15");
  await page.getByRole("button", { name: "Далее" }).click();
  await expectCaption(page, "Часовой пояс?", "select");
  await shot(page, `${tag}-onb-3-timezone`);
  await page.getByLabel("Часовой пояс").selectOption({ label: "Москва (UTC+3)" });
  // Ждём сам ответ анкеты, а не 5 с по умолчанию: в CI «Готово» оставалось disabled — запрос ещё шёл (CI 38863710119).
  const questionnaire = page.waitForResponse(
    (r) => r.url().includes("/api/onboarding/questionnaire") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Готово" }).click();
  expect((await questionnaire).ok()).toBe(true);
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();
}

test.setTimeout(180_000);
test.use({ actionTimeout: 10_000 });

for (const { name: platformName, platform } of PLATFORMS) {
  for (const width of WIDTHS) {
    for (const theme of THEMES) {
      const tag = `${platformName}-${width}-${theme}`;
      test.describe(`подписи полей: ${tag}`, () => {
        test.use({ viewport: { width, height: 800 } });

        test("онбординг и форма входов курса: подписи видны целиком", async ({ page }) => {
          page.on("dialog", (dialog) => void dialog.accept());
          const { consoleErrors, apiFailures } = await openAppAs(page, nextId(), { theme, telegram: { platform } });
          await fillOnboarding(page, tag, { baseline: true });

          // курс «Подтягивания»: форма недостающих входов V5.6 (замер 8 → уровень 1, с помощью)
          await page.getByRole("button", { name: /^Подтягивания/ }).first().click();
          await page.getByRole("button", { name: "Добавить в план" }).click();
          await expect(page.getByRole("button", { name: "В плане" })).toBeVisible();
          await openPreScreen(page, "Подтягивания");
          await expect(page.getByTestId("course-setup-required")).toBeVisible();

          await expectCaption(page, "Строгих повторений с объёмной резиной (≈8–12), повт.", "input");
          // объёмная резина — полная запись (4 поля); в силе «без помощи» разрешено, поля скрыты до снятия флажка
          for (const text of ["Резина (модель/название)", "Цвет резины", "Крепление", "Положение: стопа или колено"]) {
            await expectCaption(page, text, undefined, "course-volume-band");
          }
          await page.getByTestId("course-strength-band-bodyweight").check();
          // «Зачем это нужно»: помощь по правилам допуска, без конкретной резины и килограммов
          const why = page.getByTestId("course-setup-why");
          await expect(why).toBeVisible();
          await expect(why).toContainText("меньше 10");
          await expect(why).toContainText("не подбирает ни резину");
          await shot(page, `${tag}-course-setup`);
          const horizontal = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
          expect(horizontal, "нет горизонтального скролла").toBe(true);

          expect(noWakeLock(consoleErrors)).toEqual([]);
          expect(apiFailures).toEqual([]);
        });

        test("1RM: подписи 5×5 / 5×3 видны целиком", async ({ page }) => {
          // scripts/e2e_seed_all.sh: v5_one_rep_max 930701 — собственный профиль этого спека (930502 мутирует
          // course-v5-engine); экран только читается — ничего не сохраняется, повторные прогоны безопасны.
          const { consoleErrors, apiFailures } = await openAppAs(page, ONE_RM_USER, { theme, telegram: { platform } });
          await page.getByRole("button", { name: "Планы" }).click();
          await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
          await expect(page.getByTestId("course-setup-required")).toBeVisible();
          // Первый вход: 5×5 / 5×3 — «Вариант 2» после теста 1RM, подпись короткая, пример — в подсказке.
          await expectCaption(page, "Недавний 5×5 (сила A): дополнительный вес, кг", "input", "course-setup-known-strength");
          await expectCaption(page, "Недавний 5×3 (сила B): дополнительный вес, кг", "input", "course-setup-known-strength");
          const why = page.getByTestId("course-setup-why");
          await expect(why).toContainText("5×5 / 5×3");
          await expect(why).toContainText("Вес не назначается");
          await shot(page, `${tag}-course-1rm`);
          const horizontal = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
          expect(horizontal, "нет горизонтального скролла").toBe(true);
          expect(noWakeLock(consoleErrors)).toEqual([]);
          expect(apiFailures).toEqual([]);
        });
      });
    }
  }
}

for (const theme of THEMES) {
  test.describe(`каталог и журнал: 390 ${theme}`, () => {
    test.use({ viewport: { width: 390, height: 800 } });

    test("каталог по-человечески; карточка курса — 2 в неделю; журнал называет блоки", async ({ page }) => {
      page.on("dialog", (dialog) => void dialog.accept());
      const { consoleErrors, apiFailures } = await openAppAs(page, nextId(), { theme });
      await fillOnboarding(page, `catalog-${theme}`, { baseline: true });

      // --- каталог: подписи категорий -----------------------------------------------------------
      await expect(page.getByTestId("program-category-title").filter({ hasText: "Подтягивания" }).first()).toBeVisible();
      await expect(page.getByText(/pull[_ ]?ups/i)).toHaveCount(0);
      await shot(page, `catalog-${theme}-home`);

      await page.getByRole("button", { name: /^Подтягивания/ }).first().click();
      await expect(page.getByTestId("program-cover")).toContainText("Подтягивания");
      await expect(page.getByText(/pull[_ ]?ups/i)).toHaveCount(0);
      // карточка нового курса V5.6: 2 основных занятия в неделю; стартового «10 × 3» нет, цели — по входам
      const schedule = page.getByTestId("program-schedule");
      await expect(schedule).toBeVisible();
      await expect(schedule).toContainText("2 раза в неделю");
      await expect(schedule).toContainText("цели считаются по вашим данным");
      await expect(schedule).not.toContainText(/10 повт|× 3 подх|3 раза в неделю/);
      await shot(page, `catalog-${theme}-program-detail`);

      // --- поиск: чип категории — человеческий, и слаг программы совпадает с категорией упражнений ---
      await page.getByRole("button", { name: "Добавить в план" }).click();
      await expect(page.getByRole("button", { name: "В плане" })).toBeVisible();

      // --- проходим основное занятие и открываем детали/редактор в Журнале ---------------------------
      await openPreScreen(page, "Подтягивания");
      await expect(page.getByTestId("course-setup-required")).toBeVisible();
      await page.getByTestId("course-input-volume_capacity").fill("10");
      await page.getByTestId("course-volume-band-name").fill("Синяя");
      await page.getByTestId("course-volume-band-colour").fill("синяя");
      await page.getByTestId("course-volume-band-attachment").fill("петля на перекладине");
      await page.getByTestId("course-volume-band-position").fill("стопа");
      await page.getByTestId("course-strength-band-bodyweight").check();
      await page.getByTestId("course-setup-save").click();
      await expect(page.getByText("Блок 1: 7/7/7/7+")).toBeVisible();
      await page.getByRole("button", { name: "Начать", exact: true }).click();
      await expect(page.getByText("Живая тренировка")).toBeVisible();
      // весь занятие целиком: объём 7/7/7/7+ → 15 минут (пропуск) → сила 5/5/5/5/5–8, чтобы в редакторе были оба блока
      await playSetsV2(page, ["7", "7", "7", "7"]);
      await page.getByTestId("engine-skip").click();
      await expect(page.getByTestId("engine-phase")).toHaveText(/Приготовься|Отдых|Пошёл/);
      await playSetsV2(page, ["5", "5", "5", "5", "5"]);
      await finishV2(page, { checks: "valid" });
      await expect(page.getByText("Тренировка завершена").first()).toBeVisible();
      await page.getByRole("button", { name: "Закрыть" }).click();

      await page.reload();
      await page.getByRole("button", { name: "Журнал", exact: true }).click();
      const card = page.locator(".history-card").filter({ hasText: "Подтягивания" }).first();
      await expect(card).toBeVisible();
      await openJournalEntry(page, card, "open");
      const sections = page.locator(".block-section");
      await expect(sections.filter({ hasText: "Объём A" })).toHaveCount(1);
      await expect(sections.filter({ hasText: "Сила с помощью" })).toHaveCount(1);
      await expect(page.getByText("Упражнение", { exact: true })).toHaveCount(0);
      await shot(page, `journal-${theme}-details`);

      await page.getByRole("button", { name: /Изменить/ }).click();
      await expect(page.locator(".block-section").filter({ hasText: "Объём A" })).toHaveCount(1);
      await expect(page.locator(".block-section").filter({ hasText: "Сила с помощью" })).toHaveCount(1);
      await shot(page, `journal-${theme}-editor`);

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}

for (const { reps, headline, line } of [
  { reps: 12, headline: "допуск к работе с весом", line: "тест 1RM" },
  { reps: 16, headline: "дополнительным весом", line: "тест 1RM" },
]) {
  test(`сразу после замера ${reps}: нужен вес, а не резина — обычный пользователь`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 800 });
    const { consoleErrors, apiFailures } = await openAppAs(page, nextId());
    await page.getByLabel("Сколько подтягиваний вышло?").fill(String(reps));
    await page.getByRole("button", { name: "Далее" }).click();
    await page.getByRole("button", { name: "Да" }).click();
    const qualification = page.getByTestId("baseline-qualification");
    await expect(qualification).toContainText(`Замер ${reps}`);
    await expect(qualification).toContainText(headline);
    await expect(qualification).toContainText(line);
    await expect(qualification).not.toContainText("Вам понадобится резина");
    await expect(qualification).not.toContainText(/\d+\s?кг/);
    await shot(page, `after-baseline-${reps}`);
    // следующий шаг ведёт в существующий поток: Продолжить → анкета
    await page.getByRole("button", { name: "Продолжить" }).click();
    await expect(page.getByLabel("Твой вес в кг?")).toBeVisible();
    expect(noWakeLock(consoleErrors)).toEqual([]);
    expect(apiFailures).toEqual([]);
  });
}
