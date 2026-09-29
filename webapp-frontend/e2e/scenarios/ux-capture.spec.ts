import { test, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

import { openAppAs } from "../fixtures/setup";

// Reusable black-box capture of OUR app for docs/REFERENCE_UX_REVIEW.md.
// Skipped unless UX_CAPTURE=1. Output: $UX_CAPTURE_DIR/<label>/<width>/<name>.png + <name>.txt
// (visible text + accessibility-relevant controls), so shots can be paired with Crimpd
// captures by name. Seeds: scripts/e2e_seed_all.sh (920003 Builder, 910001 execution).
test.skip(!process.env.UX_CAPTURE, "set UX_CAPTURE=1 to capture screens");
test.setTimeout(180_000);

const LABEL = process.env.UX_LABEL ?? "ours";
const OUT = process.env.UX_CAPTURE_DIR ?? path.resolve("ux-captures");
const WIDTHS = (process.env.UX_WIDTHS ?? "390,320").split(",").map(Number);

async function shot(page: Page, width: number, name: string) {
  const dir = path.join(OUT, LABEL, String(width));
  fs.mkdirSync(dir, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(dir, `${name}.png`), fullPage: true });
  const controls = await page.evaluate(() =>
    Array.from(document.querySelectorAll("button, input, textarea, select, [role=tab]"))
      .map((el) => {
        const e = el as HTMLInputElement;
        return `${el.tagName.toLowerCase()}${e.type ? `[${e.type}]` : ""}: ${(el.textContent || e.value || e.placeholder || e.getAttribute("aria-label") || "").trim().slice(0, 60)}`;
      }),
  );
  const text = await page.evaluate(() => document.body.innerText);
  fs.writeFileSync(path.join(dir, `${name}.txt`), `${text}\n\n--- controls ---\n${controls.join("\n")}\n`);
}

for (const width of WIDTHS) {
  test(`capture builder+home @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await openAppAs(page, 920_003);
    await page.getByTestId("my-workouts").waitFor();
    await shot(page, width, "01_home");

    await page.getByRole("button", { name: "Создать", exact: true }).click();
    await shot(page, width, "02_create_entry");
    await page.getByRole("textbox").fill("UX Capture");
    await page.getByRole("button", { name: /^(Сохранить|Создать и добавить упражнения)$/ }).click();
    await page.getByText("Редактировать тренировку").waitFor();
    await shot(page, width, "03_editor_empty");

    await page.getByRole("button", { name: /^(\+ )?Добавить упражнение$/ }).click();
    await shot(page, width, "04_exercise_picker");
    await page.locator(".program-card-button, .ux-pick").first().click();
    await shot(page, width, "05_protocol_reps");
    for (const [label, name] of [["Время", "06_protocol_time"], ["Максимум", "07_protocol_max"], ["Интервалы", "08_protocol_interval"]]) {
      await page.getByRole(await page.getByRole("radio", { name: label }).count() ? "radio" : "tab", { name: new RegExp(`^${label}`) }).click();
      await shot(page, width, name);
    }
    await page.getByRole(await page.getByRole("radio").count() ? "radio" : "tab", { name: /^Повторения/ }).first().click();
    await page.getByRole("button", { name: /^(Добавить|Готово|Добавить упражнение)$/ }).last().click();
    await shot(page, width, "09_editor_with_item");

    await page.getByRole("button", { name: "Сохранить" }).last().click();
    await page.getByTestId("my-workouts").waitFor();
    await page.getByTestId("my-workout-card").filter({ hasText: "Очень длинная" }).click();
    await page.getByText("Редактировать тренировку").waitFor();
    await shot(page, width, "10_workout_detail_edit");
    await page.getByRole("button", { name: "Добавить в план" }).click();
    await shot(page, width, "11_add_to_plan");
  });

  test(`capture execution @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await openAppAs(page, 910_001);
    await page.getByRole("button", { name: "Планы" }).click();
    await shot(page, width, "20_plans");
    const group = page.locator(".plan-week-day-group").filter({ hasText: /^Смешанная|Смешан/ }).first();
    await group.getByRole("button", { name: "Начать", exact: true }).click();
    await shot(page, width, "21_pre_start");
    await page.getByRole("button", { name: "Начать", exact: true }).click();
    await page.getByText("Живая тренировка").waitFor();
    await shot(page, width, "22_live_set_ready");
    await page.getByRole("button", { name: "Готов", exact: true }).click();
    await page.getByText("Пошёл").waitFor();
    await shot(page, width, "23_live_set_running");
  });
}
