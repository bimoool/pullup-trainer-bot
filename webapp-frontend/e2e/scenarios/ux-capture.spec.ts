import { test, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

import { clickAndSync, playSets } from "../fixtures/builderFlow";
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
const THEME = process.env.UX_THEME === "dark" ? "dark" : "light";

async function shot(page: Page, width: number, name: string, fullPage = !name.startsWith("01_")) {
  const dir = path.join(OUT, LABEL, String(width));
  fs.mkdirSync(dir, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(dir, `${name}.png`), fullPage });
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
    await page.getByLabel("Повторений").fill("8");
    await clickAndSync(page, "Готово", "/sets:batch");
    await clickAndSync(page, "Пропустить отдых", "/phase/next");
    await playSets(page, ["8"]);
    await page.getByText("Следующее упражнение").waitFor();
    await shot(page, width, "24_block_transition");
  });

  // Все пять вкладок + Workout Detail (#280): паттерны оболочки сравниваются с эталоном.
  test(`capture tabs @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await openAppAs(page, 940_001, { theme: THEME });
    await page.getByTestId("my-workouts").waitFor();
    await shot(page, width, "30_home_tab");
    await shot(page, width, "30_home_tab_vp", false);
    await page.getByTestId("my-workout-card").first().click();
    await page.getByTestId("workout-detail").waitFor();
    await shot(page, width, "31_workout_detail");
    await shot(page, width, "31_workout_detail_vp", false);

    for (const [id, tab, name, ready] of [
      [900_013, "Планы", "32_plans_tab", null],
      [910_002, "Журнал", "33_journal_tab", null],
      [910_003, "Аналитика", "34_analytics_tab", null],
      [900_003, "Профиль", "35_profile_tab", null],
    ] as const) {
      void ready;
      await page.goto("about:blank");
      await openAppAs(page, id, { theme: THEME });
      await page.locator(".bottom-tabbar").getByRole("button", { name: tab }).click();
      await page.waitForTimeout(1200);
      await shot(page, width, name);
      await shot(page, width, `${name}_vp`, false);
    }

    // Поиск, Program Detail и хаб «Тесты» с Главной (#280).
    await page.goto("about:blank");
    await openAppAs(page, 940_001, { theme: THEME });
    await page.getByTestId("home-search-pill").click();
    await page.waitForTimeout(600);
    await shot(page, width, "36_search_vp", false);
    await page.goto("about:blank");
    await openAppAs(page, 940_001, { theme: THEME });
    await page.locator(".program-card-button").first().click();
    await page.waitForTimeout(600);
    await shot(page, width, "37_program_detail_vp", false);
    await page.goto("about:blank");
    await openAppAs(page, 940_001, { theme: THEME });
    await page.getByTestId("home-tests-row").click();
    await page.waitForTimeout(800);
    await shot(page, width, "38_tests_hub_vp", false);
  });
}
