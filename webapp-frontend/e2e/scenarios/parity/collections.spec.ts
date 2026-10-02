import { expect, test } from "@playwright/test";

import { expectNoHorizontalOverflow, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import { isTelegramBackButtonVisible, pressTelegramBackButton } from "../../fixtures/telegramMock";

// Collections (#271, Crimpd H5 / D1). Seed: scripts/e2e_seed.py collections — опубликованная
// «E2E: подборка» (программы «Подборка: сила» и «Подборка: гибкость», system-упражнение
// «Подборка: упражнение»; приватное упражнение пользователя в составе не показывается) и
// неопубликованный «E2E: черновик». Только чтение: один пользователь на ширину/тему.
const USERS = { 320: { id: 999_401, theme: "light" }, 390: { id: 999_411, theme: "dark" } } as const;

for (const width of WIDTHS) {
  const user = USERS[width as 320 | 390];

  test.describe(`Collections @${width}px ${user.theme}`, () => {
    test.use({ viewport: { width, height: 760 } });

    test("Главная: ряд «Подборки» с карточкой (автор, название, состав, описание); черновик скрыт", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, user.id, { theme: user.theme });

      const row = page.getByTestId("collections-row");
      await expect(row).toBeVisible();
      await expect(row.locator(".section-title")).toHaveText("Подборки");
      const card = row.getByTestId("collection-card").filter({ hasText: "E2E: подборка" });
      await expect(card).toBeVisible();
      await expect(card.getByTestId("collection-card-author")).toHaveText("Турникмэн");
      await expect(card.getByTestId("collection-card-title")).toHaveText("E2E: подборка");
      // 2 программы + 1 system-упражнение; приватное упражнение в счёт не входит.
      await expect(card.getByTestId("collection-card-count")).toHaveText("3 элемента");
      await expect(card).toContainText("две программы и упражнение");
      await expect(row.getByText("E2E: черновик")).toHaveCount(0);

      // Каталог программ остаётся на месте и не цепляется за карточки подборок.
      await expect(page.getByTestId("program-category").first()).toBeVisible();
      await expectNoHorizontalOverflow(page, "Главная с рядом «Подборки»");

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("Главная: без подборок ряд «Подборки» скрыт целиком (и при сбое запроса)", async ({ page }) => {
      await page.route("**/api/v2/collections", (route) => route.fulfill({ json: { collections: [] } }));
      const { consoleErrors } = await openAppAs(page, user.id, { theme: user.theme });

      await expect(page.getByTestId("program-category").first()).toBeVisible();
      await expect(page.getByTestId("collections-row")).toHaveCount(0);
      await expect(page.getByText("Подборки", { exact: true })).toHaveCount(0);
      expect(consoleErrors).toEqual([]);
    });

    test("программа из подборки, пока каталог грузится: «Загружаю программу…», «Назад» работает, затем открывается Program Detail (#283)", async ({ page }) => {
      let release: () => void = () => undefined;
      const gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      await page.route("**/api/v2/programs", async (route) => {
        await gate;
        await route.continue();
      });
      const { consoleErrors, apiFailures } = await openAppAs(page, user.id, { theme: user.theme });

      await page.getByTestId("collection-card").filter({ hasText: "E2E: подборка" }).click();
      await expect(page.getByTestId("collection-item")).toHaveCount(3);
      await page.getByTestId("collection-item").nth(0).click();
      await expect(page.getByTestId("program-pending-loading")).toHaveText("Загружаю программу…");
      await expectNoHorizontalOverflow(page, "Подборка: программа, каталог грузится");

      // «Назад» из ожидания возвращает в подборку, не в тупик.
      await page.getByRole("button", { name: "← Назад" }).click();
      await expect(page.getByTestId("collection-screen")).toBeVisible();
      await page.getByTestId("collection-item").nth(0).click();
      await expect(page.getByTestId("program-pending-loading")).toBeVisible();

      release();
      await expect(page.getByTestId("program-detail-title")).toHaveText("Подборка: сила");
      await page.getByRole("button", { name: "← Назад" }).click();
      await expect(page.getByTestId("collection-screen")).toBeVisible();
      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("программа из подборки, каталог не загрузился: понятная ошибка и «Назад» в подборку (#283)", async ({ page }) => {
      await page.route("**/api/v2/programs", (route) =>
        route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "catalog down" }) }),
      );
      await openAppAs(page, user.id, { theme: user.theme, allowedApiStatuses: [500] });

      await page.getByTestId("collection-card").filter({ hasText: "E2E: подборка" }).click();
      await page.getByTestId("collection-item").nth(0).click();
      await expect(page.getByTestId("program-pending-error")).toContainText("Не удалось загрузить программу");
      await expectNoHorizontalOverflow(page, "Подборка: программа, каталог упал");
      await page.getByRole("button", { name: "← Назад" }).click();
      await expect(page.getByTestId("collection-screen")).toBeVisible();
    });

    test("экран подборки: шапка и список; программа и упражнение открывают свои экраны, «Назад» не ведёт в тупик", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, user.id, { theme: user.theme, backButton: true });

      await page.getByTestId("collection-card").filter({ hasText: "E2E: подборка" }).click();
      await expect(page.getByTestId("collection-screen")).toBeVisible();
      await expect(page.getByTestId("collections-row")).toHaveCount(0);
      expect(await isTelegramBackButtonVisible(page)).toBe(true);

      await expect(page.getByTestId("collection-title")).toHaveText("E2E: подборка");
      await expect(page.getByTestId("collection-author")).toHaveText("Турникмэн");
      await expect(page.getByTestId("collection-count")).toHaveText("3 элемента");
      await expect(page.getByTestId("collection-description")).toContainText("две программы и упражнение");

      const items = page.getByTestId("collection-item");
      await expect(items).toHaveCount(3);
      await expect(items.nth(0)).toContainText("Подборка: сила");
      await expect(items.nth(1)).toContainText("Подборка: гибкость");
      await expect(items.nth(2)).toContainText("Подборка: упражнение");
      await expect(page.getByText("Подборка: приватное")).toHaveCount(0);
      await expectNoHorizontalOverflow(page, "Экран подборки");

      // Программа → существующий Program Detail; «Назад» возвращает в подборку.
      await items.nth(0).click();
      await expect(page.getByTestId("program-detail-title")).toHaveText("Подборка: сила");
      await expect(page.getByRole("button", { name: "Добавить в план" })).toBeEnabled();
      await expectNoHorizontalOverflow(page, "Program Detail из подборки");
      await page.getByRole("button", { name: "← Назад" }).click();
      await expect(page.getByTestId("collection-screen")).toBeVisible();
      await expect(page.getByTestId("collection-item")).toHaveCount(3);

      // Упражнение → существующий экран «Добавить в план»; BackButton Telegram возвращает в подборку.
      await page.getByTestId("collection-item").nth(2).click();
      await expect(page.getByText("Добавить в план", { exact: true })).toBeVisible();
      await expect(page.getByText("Подборка: упражнение", { exact: true })).toBeVisible();
      await pressTelegramBackButton(page);
      await expect(page.getByTestId("collection-screen")).toBeVisible();

      // Назад из подборки — на Главную с рядом.
      await page.getByRole("button", { name: "← Назад" }).click();
      await expect(page.getByTestId("collections-row")).toBeVisible();
      await expect(page.getByTestId("collection-screen")).toHaveCount(0);

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
