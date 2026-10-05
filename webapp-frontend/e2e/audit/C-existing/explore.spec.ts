import { test } from "@playwright/test";
import { Log, open, shot, body, tab } from "./lib";
test("explore legacy edit", async ({ page }) => {
  const log = new Log("explore");
  try {
  await open(page, 7300002, log);
  await page.waitForTimeout(2500);
  await tab(page, "Журнал");
  await page.getByRole("button", { name: "Изменить" }).first().click();
  await page.waitForTimeout(1500);
  log.add("V_EDIT", await body(page));
  log.add("BUTTONS", JSON.stringify(await page.getByRole("button").allInnerTexts()));
  log.add("INPUTS", JSON.stringify(await page.locator("input,textarea,select").evaluateAll(els=>els.map(e=>[e.tagName,e.getAttribute("type"),e.getAttribute("aria-label"),e.getAttribute("placeholder"),(e as HTMLInputElement).value]))));
  await shot(page, log, "legacy_edit");
  } finally { log.flush(); }
});
