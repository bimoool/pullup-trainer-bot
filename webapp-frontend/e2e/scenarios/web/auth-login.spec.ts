import { expect, request as playwrightRequest, test } from "@playwright/test";

import {
  authUserId, botAction, countUsers, getJson, miniAppHeaders, readRequestId, startLogin,
} from "../../fixtures/webAuth";

// WEB-AUTH: вход в обычном браузере через бота. Проекты web-desktop / web-mobile. Сид home_workouts (942011–942028).
const SENTINEL = { "X-Telegram-Init-Data": "web-session" };

async function expectSignedIn(page: import("@playwright/test").Page) {
  await expect(page.getByTestId("login-screen")).toHaveCount(0);
  await expect(page.locator(".plan-title")).toHaveText("Главная");
  await expect(page.getByTestId("my-workout-card")).toHaveCount(2);
}

test("без сессии и без Telegram открывается экран входа, а не ошибка", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("login-screen")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Вход через Telegram" })).toBeVisible();
  await expect(page.getByTestId("login-start")).toBeEnabled();
  await expect(page.locator("body")).not.toContainText("initDataRaw");
});

test("вход через бота: тот же аккаунт, что в Mini App, один ряд users, сессия переживает перезагрузку", async ({ page }, testInfo) => {
  const id = authUserId(testInfo, 1);
  expect(countUsers(id)).toBe(1);
  const { requestId, code } = await startLogin(page);

  // Пока не подтверждено — экран ждёт, сессии нет.
  await expect(page.getByTestId("login-countdown")).toContainText("Осталось");
  expect((await page.request.get("/api/web-auth/session")).ok()).toBe(true);
  expect(await (await page.request.get("/api/web-auth/session")).json()).toMatchObject({ authenticated: false });

  // «В Telegram»: бот показывает тот же код и просит подтвердить.
  const messages = botAction(requestId, id, "confirm");
  expect(messages.some((text) => text.includes(code))).toBe(true);
  expect(messages.join("\n")).toContain("Готово. Вернитесь в браузер");

  await expectSignedIn(page);
  expect(countUsers(id)).toBe(1);

  // Те же данные, что видит Mini App у этого пользователя.
  const viaBrowser = await getJson(page.request, "/api/v2/dashboard/status", SENTINEL);
  const miniApp = await playwrightRequest.newContext({ baseURL: testInfo.project.use.baseURL });
  const viaTelegram = await getJson(miniApp, "/api/v2/dashboard/status", miniAppHeaders(id));
  await miniApp.dispose();
  expect(viaBrowser).toEqual(viaTelegram);

  // Cookie HttpOnly: из JS не виден, в хранилищах токена нет.
  const cookies = await page.context().cookies();
  const session = cookies.find((c) => c.name === "pullup_web_session");
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe("Lax");
  const visible = await page.evaluate(() => document.cookie + JSON.stringify(localStorage) + JSON.stringify(sessionStorage));
  expect(visible).not.toContain(session!.value);

  await page.reload();
  await expectSignedIn(page);
});

test("выход: сессия отозвана на сервере, после перезагрузки снова экран входа", async ({ page }, testInfo) => {
  const id = authUserId(testInfo, 2);
  const { requestId } = await startLogin(page);
  botAction(requestId, id, "confirm");
  await expectSignedIn(page);
  const stolen = (await page.context().cookies()).find((c) => c.name === "pullup_web_session")!.value;

  const signOut = page.getByTestId("sign-out");
  if ((await signOut.count()) > 0) {
    await signOut.click(); // кнопка добавляется координатором (WEB-AUTH-seam-request.md)
  } else {
    expect((await page.request.post("/api/web-auth/logout", { headers: SENTINEL })).ok()).toBe(true);
  }
  await page.reload();
  await expect(page.getByTestId("login-screen")).toBeVisible();

  // Украденный/старый токен после выхода не работает.
  const replay = await playwrightRequest.newContext({
    baseURL: testInfo.project.use.baseURL, extraHTTPHeaders: { Cookie: `pullup_web_session=${stolen}` },
  });
  expect((await replay.get("/api/hello", { headers: SENTINEL })).status()).toBe(401);
  await replay.dispose();
});

test("отмена в Telegram: экран сообщает и предлагает новый код, входа нет", async ({ page }, testInfo) => {
  const id = authUserId(testInfo, 3);
  const { requestId } = await startLogin(page);
  botAction(requestId, id, "deny");
  await expect(page.getByTestId("login-denied")).toBeVisible();
  expect(await (await page.request.get("/api/web-auth/session")).json()).toMatchObject({ authenticated: false });
  await page.getByTestId("login-retry").click();
  await expect(page.getByTestId("login-code")).toBeVisible();
  expect(await readRequestId(page)).not.toBe(requestId);
});

test("запрос истёк: экран сообщает об этом и предлагает новый код", async ({ page }) => {
  // 5 минут не ждём — сокращаем срок в ответе создания; серверный срок (в т.ч. отказ после него) проверяют pytest.
  await page.route("**/api/web-auth/login-requests", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, expires_in_seconds: 2 } });
  });
  await startLogin(page);
  await expect(page.getByTestId("login-expired")).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("login-retry").click();
  await expect(page.getByTestId("login-code")).toBeVisible();
});

test("неверный секрет: опрос чужим секретом не входит и не раскрывает существование запроса", async ({ page, request }, testInfo) => {
  const id = authUserId(testInfo, 5);
  const { requestId } = await startLogin(page);
  botAction(requestId, id, "confirm");
  const wrong = await request.post(`/api/web-auth/login-requests/${requestId}/poll`, { headers: { "X-Web-Login-Secret": "guess" } });
  const unknown = await request.post(`/api/web-auth/login-requests/${"0".repeat(32)}/poll`, { headers: { "X-Web-Login-Secret": "guess" } });
  expect(wrong.status()).toBe(404);
  expect(await wrong.json()).toEqual(await unknown.json());
  await expectSignedIn(page); // настоящий браузер со своим секретом при этом входит
});

test("повторное нажатие «Подтвердить» и чужая ссылка не дают второй сессии и не плодят аккаунты", async ({ page }, testInfo) => {
  const id = authUserId(testInfo, 6);
  const { requestId } = await startLogin(page);
  botAction(requestId, id, "confirm");
  await expectSignedIn(page);
  const second = botAction(requestId, id, "confirm");
  expect(second.join("\n")).toContain("устарела или уже использована");
  expect(countUsers(id)).toBe(1);
});

test("тестовый вход: на стенде с WEB_AUTH_TEST_LOGIN=1 открывает сессию, иначе маршрута нет", async ({ request }, testInfo) => {
  const response = await request.post("/api/web-auth/test-login", { data: { telegram_id: authUserId(testInfo, 7) } });
  if (process.env.WEB_AUTH_TEST_LOGIN === "1") {
    expect(response.status()).toBe(200);
    expect(await (await request.get("/api/web-auth/session")).json()).toMatchObject({ authenticated: true });
  } else {
    expect(response.status()).toBe(404);
  }
});
