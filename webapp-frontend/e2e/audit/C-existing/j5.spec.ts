import { test } from "@playwright/test";
import { Log, open, shot, body, tab } from "./lib";

async function analyticsCount(page: any, log: Log, label: string) {
  await tab(page, "Аналитика");
  const b = await body(page);
  const m = b.match(/(\d+) \| Тренировок за 30 дней/);
  log.add("VISIBLE", `Аналитика(${label}) Тренировок за 30 дней=${m?.[1]} :: ` + b.slice(0, 260));
  return m ? Number(m[1]) : -1;
}

test("J5a native v2 session + backdated activity (audit_existing_active)", async ({ page }) => {
  const log = new Log("J5a_audit_existing_active");
  try {
    log.add("JOURNEY", "J5 Journal lifecycle  PROFILE audit_existing_active (tg 7300001)  S0: native v2 session produced via UI in J1 (2 sets of 10)");
    await open(page, 7300001, log);
    await page.waitForTimeout(2500);
    const c0 = await analyticsCount(page, log, "before");
    await tab(page, "Журнал");
    log.add("TAP", "native plan session entry 'По плану'");
    await page.getByText("По плану").first().click();
    await page.waitForTimeout(1000);
    const sheet = await page.getByRole("button").allInnerTexts();
    log.add("EXPECT", "action sheet offers Открыть / Изменить / Повторить / Удалить");
    const hasEdit = sheet.some((t) => /Изменить/.test(t));
    log.add("ACTUAL", JSON.stringify(sheet.filter((t) => /Открыть|Изменить|Повторить|Удалить|Отмена/.test(t))), hasEdit ? "OK" : "FAIL F-C-05 (no Изменить/Повторить/Удалить for native plan session)");
    await shot(page, log, "j5a_01_native_sheet");
    await page.getByRole("button", { name: "Открыть" }).click();
    await page.waitForTimeout(1500);
    log.add("VISIBLE", "native detail :: " + await body(page));
    log.add("EXPECT", "exercise names in detail (Подтягивания — объём / сила)");
    const detail = await body(page);
    log.add("ACTUAL", detail, /Упражнение \| План/.test(detail) ? "FAIL F-C-06 (both blocks titled 'Упражнение')" : "OK");
    const dBtns = await page.getByRole("button").allInnerTexts();
    log.add("ACTUAL", "detail buttons " + JSON.stringify(dBtns), dBtns.some((t) => /Изменить/.test(t)) ? "OK" : "FAIL F-C-05");
    await shot(page, log, "j5a_02_native_detail");

    // ---- backdate a disposable entry through UI
    await page.reload(); await page.waitForTimeout(2500);
    await tab(page, "Журнал");
    log.add("TAP", "+ Записать → Другую активность (backdate 2026-10-02)");
    await page.getByRole("button", { name: "+ Записать" }).click();
    await page.getByRole("button", { name: "Другую активность" }).click();
    await page.locator("input[type=date]").fill("2026-10-02");
    await page.locator("select").selectOption({ label: "Плавание" });
    await page.getByPlaceholder("1:30").fill("0:40");
    await page.getByRole("button", { name: /^4/ }).click();
    await page.getByRole("button", { name: "Сохранить" }).click();
    await page.waitForTimeout(1800);
    log.add("VISIBLE", "after save :: " + await body(page));
    await page.reload(); await page.waitForTimeout(2500);
    await tab(page, "Журнал");
    const afterReload = await body(page);
    log.add("EXPECT", "Плавание 0:40 present after reload");
    log.add("ACTUAL", afterReload.slice(0, 500), /Плавание/.test(afterReload) ? "OK" : "FAIL F-C-07");
    const c1 = await analyticsCount(page, log, "after backdated add");
    log.add("EXPECT", "Аналитика count changes after adding an activity (informational)");
    log.add("ACTUAL", `before=${c0} after=${c1}`, c1 > c0 ? "OK" : "NOTE activities not counted in 'Тренировок за 30 дней'");

    // edit
    await tab(page, "Журнал");
    await page.getByText("Плавание").first().click();
    await page.getByRole("button", { name: "Изменить" }).first().click();
    await page.waitForTimeout(1200);
    log.add("VISIBLE", "edit form :: " + await body(page));
    await shot(page, log, "j5a_03_edit_form");
    log.add("EXPECT", "edit form allows changing duration (0:40) — observed form has only date/rating/comment");
    log.add("ACTUAL", "no duration field in edit form", "NOTE F-C-08 duration not editable");
    await page.locator("select").selectOption("2");
    await page.locator("textarea").fill("audit edit");
    await page.getByRole("button", { name: "Сохранить" }).click();
    await page.waitForTimeout(1800);
    await page.reload(); await page.waitForTimeout(2500);
    await tab(page, "Журнал");
    const afterEdit = await body(page);
    log.add("EXPECT", "Усилие 2 on Плавание after edit+reload");
    log.add("ACTUAL", afterEdit.slice(0, 600), /Плавание \| 12:00 \| Длительность \| 0:40 \| Дистанция \| — \| Усилие \| 2/.test(afterEdit) ? "OK" : "FAIL F-C-08");

    // clone
    await page.getByText("Плавание").first().click();
    await page.getByRole("button", { name: "Повторить" }).first().click();
    await page.waitForTimeout(1500);
    log.add("VISIBLE", "after Повторить :: " + await body(page));
    await shot(page, log, "j5a_04_clone");
    await page.getByRole("button", { name: "Создать копию" }).click(); await page.waitForTimeout(1800);
    log.add("VISIBLE", "after Создать копию :: " + (await body(page)).slice(0, 500));
    await page.reload(); await page.waitForTimeout(2500);
    await tab(page, "Журнал");
    const afterClone = await body(page);
    const swims = (afterClone.match(/Плавание/g) || []).length;
    log.add("EXPECT", "2 Плавание entries after clone");
    log.add("ACTUAL", `count=${swims} :: ` + afterClone.slice(0, 600), swims >= 2 ? "OK" : "FAIL F-C-09");
    const c2 = await analyticsCount(page, log, "after clone");

    // delete both disposables
    for (let k = 0; k < 2; k++) {
      await tab(page, "Журнал");
      if (!(await page.getByText("Плавание").count())) break;
      await page.getByText("Плавание").first().click();
      await page.getByRole("button", { name: "Удалить" }).first().click();
      await page.waitForTimeout(800);
      log.add("VISIBLE", "after Удалить tap (native confirm accepted, see DIALOG) :: " + (await body(page)).slice(0, 200));
      await page.waitForTimeout(1500);
    }
    await page.reload(); await page.waitForTimeout(2500);
    await tab(page, "Журнал");
    const afterDel = await body(page);
    log.add("EXPECT", "no Плавание after delete+reload");
    log.add("ACTUAL", afterDel.slice(0, 500), /Плавание/.test(afterDel) ? "FAIL F-C-10" : "OK");
    const c3 = await analyticsCount(page, log, "after delete");
    log.add("INFO", `analytics counts: before=${c0} afterAdd=${c1} afterClone=${c2} afterDelete=${c3}`);
    await shot(page, log, "j5a_05_final");
  } finally { log.flush(); }
});
