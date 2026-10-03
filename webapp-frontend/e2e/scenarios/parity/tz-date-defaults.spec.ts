import { expect, test } from "@playwright/test";

import { openTab } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// #294: даты по умолчанию и max= считаются в часовом поясе ПРОФИЛЯ (Москва в сиде tests_hub), а не по часам
// устройства; сервер проверяет «дата не в будущем» тоже в поясе профиля.
// Сервер живёт по реальному времени, поэтому пояс устройства подбирается так, чтобы его календарный день ОТЛИЧАЛСЯ
// от московского прямо сейчас: Москва уже ≥ 13:00 — Pacific/Kiritimati (UTC+14, день впереди), иначе Etc/GMT+12
// (UTC−12, день позади). Для «впереди» старый код падал с «Дата не может быть в будущем» (воспроизведение #294).
const MOSCOW = "Europe/Moscow";
const dayIn = (timeZone: string, offsetDays = 0) =>
  new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date(Date.now() + offsetDays * 86_400_000));
const moscowHour = Number(new Intl.DateTimeFormat("en-GB", { timeZone: MOSCOW, hour: "2-digit", hourCycle: "h23" }).format(new Date()));
const DEVICE_ZONE = moscowHour >= 13 ? "Pacific/Kiritimati" : "Etc/GMT+12";
const BASE = 984_001; // tests_hub ×4: 984001/984002 (320 light), 984011/984012 (390 dark); +retry

test.describe("Даты по умолчанию — день профиля, не устройства (#294)", () => {
  test.use({ timezoneId: DEVICE_ZONE, viewport: { width: 390, height: 800 } });
  test.setTimeout(90_000);

  test("предусловие: день устройства отличается от дня профиля", async () => {
    expect(dayIn(DEVICE_ZONE)).not.toEqual(dayIn(MOSCOW));
  });

  test("Тесты: дата по умолчанию и max — сегодня профиля, результат записывается", async ({ page }, testInfo) => {
    const { consoleErrors, apiFailures } = await openAppAs(page, BASE + testInfo.retry, { theme: "light" });
    await page.getByTestId("home-tests-row").click();
    await page.getByTestId("test-card").filter({ hasText: "Максимум подтягиваний" }).click();
    const form = page.getByTestId("test-form");
    const date = form.getByLabel("Дата");
    await expect(date).toHaveValue(dayIn(MOSCOW));
    await expect(date).toHaveAttribute("max", dayIn(MOSCOW));
    const before = await page.getByTestId("test-history-row").count();
    await form.getByLabel("Результат, повт.").fill("11");
    await form.getByRole("button", { name: "Записать результат" }).click();
    await expect(page.getByTestId("test-history-row")).toHaveCount(before + 1);
    await expect(form.getByText("Дата не может быть в будущем")).toHaveCount(0);
    expect(consoleErrors).toEqual([]);
    expect(apiFailures).toEqual([]);
  });

  test("Журнал «+ Записать»: дата по умолчанию и max — сегодня профиля, активность сохраняется", async ({ page }, testInfo) => {
    const { consoleErrors, apiFailures } = await openAppAs(page, BASE + 10 + testInfo.retry, { theme: "dark" });
    await openTab(page, "Журнал");
    await page.getByTestId("journal-log-button").click();
    await page.getByTestId("log-option-activity").click();
    const date = page.getByTestId("log-date");
    await expect(date).toHaveValue(dayIn(MOSCOW));
    await expect(date).toHaveAttribute("max", dayIn(MOSCOW));
    await page.getByTestId("log-duration").fill("0:45");
    await page.getByTestId("log-save").click();
    await expect(page.getByTestId("log-error")).toHaveCount(0);
    await expect(page.locator(".history-card-clickable").filter({ hasText: "Бег" })).toHaveCount(1);
    expect(consoleErrors).toEqual([]);
    expect(apiFailures).toEqual([]);
  });
});
