import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { expect, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

import { buildInitData, getTestBotToken } from "./initData";

const REPO_ROOT = fileURLToPath(new URL("../../../", import.meta.url));

/** Диапазон WEB-AUTH 942010–942018 (desktop) / 942020–942028 (mobile): сид `home_workouts`, только чтение. */
export function authUserId(testInfo: TestInfo, slot: number): number {
  return (testInfo.project.name === "web-mobile" ? 942_020 : 942_010) + slot;
}

/** То, что в Telegram делает бот: /start weblogin_<id> + «Подтвердить»/«Отмена» — через настоящий aiogram-роутинг. */
export function botAction(requestId: string, telegramId: number, action: "confirm" | "deny" | "open"): string[] {
  const out = execFileSync(
    process.env.PYTHON ?? process.env.E2E_PYTHON ?? "python",
    ["scripts/e2e_web_login.py", requestId, String(telegramId), action],
    { cwd: REPO_ROOT, env: { ...process.env, PYTHONPATH: "." }, encoding: "utf8" },
  );
  return (JSON.parse(out.trim().split("\n").pop() ?? "{}") as { messages: string[] }).messages;
}

export function countUsers(telegramId: number): number {
  const out = execFileSync(
    process.env.PYTHON ?? process.env.E2E_PYTHON ?? "python",
    ["scripts/e2e_web_login.py", "-", String(telegramId), "count"],
    { cwd: REPO_ROOT, env: { ...process.env, PYTHONPATH: "." }, encoding: "utf8" },
  );
  return (JSON.parse(out.trim().split("\n").pop() ?? "{}") as { users: number }).users;
}

/** id запроса входа: из ссылки t.me (если задан BOT_USERNAME) или из подсказки со строкой /start weblogin_<id>. */
export async function readRequestId(page: Page): Promise<string> {
  const link = page.getByTestId("login-bot-link");
  const raw = (await link.count()) > 0
    ? (await link.getAttribute("href")) ?? ""
    : (await page.getByTestId("login-no-link").textContent()) ?? "";
  const match = raw.match(/weblogin_([0-9a-f]{32})/);
  expect(match, `request id not found in: ${raw}`).not.toBeNull();
  return match![1];
}

export async function startLogin(page: Page): Promise<{ requestId: string; code: string }> {
  await page.goto("/");
  await page.getByTestId("login-start").click();
  const code = (await page.getByTestId("login-code").textContent())?.trim() ?? "";
  expect(code).toMatch(/^\d{4}$/);
  return { requestId: await readRequestId(page), code };
}

/** Данные того же пользователя «как Mini App»: подписанный initData тестового токена, без cookie. */
export function miniAppHeaders(telegramId: number): Record<string, string> {
  return { "X-Telegram-Init-Data": buildInitData({ id: telegramId, firstName: "E2E" }, getTestBotToken()) };
}

export async function getJson(request: APIRequestContext, path: string, headers: Record<string, string>): Promise<unknown> {
  const response = await request.get(path, { headers });
  expect(response.status(), `${path}`).toBe(200);
  return response.json();
}
