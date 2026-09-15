import type { Page } from "@playwright/test";

/**
 * Ожидаемый шум, не баг (найдено при разборе первого реального прогона в
 * CI, issue #126): `webapp-frontend/src/main.tsx` оборачивает
 * `@telegram-apps/sdk`'s `init()` в try/catch и намеренно логирует через
 * `console.error("Telegram SDK init() failed", ...)` (issue #24 — иначе
 * необработанное исключение здесь роняло рендер до первого <p>Загрузка…</p>).
 * `init()` внутри себя сам зовёт тот же `retrieveLaunchParams()`, что и
 * App.tsx — а он гарантированно бросает исключение в этом наборе:
 * `telegramMock.ts` кладёт initData в `window.Telegram.WebApp.initData`
 * (мост telegram-web-app.js), но НЕ вписывает launch-параметры в URL/
 * performance entry/sessionStorage, единственные источники, которые читает
 * retrieveLaunchParams() — App.tsx на этот случай имеет собственный фолбэк
 * (issue #23), а вот init() в main.tsx — нет, и не обязан: он ловит
 * исключение сам и продолжает работу с дефолтной версией SDK, ровно как
 * задумано issue #24. Без этого фильтра ЛЮБОЙ сценарий этого набора падал
 * бы на `expect(consoleErrors).toEqual([])` из-за ожидаемого, а не
 * найденного бага — реальные ошибки приложения по-прежнему ловятся.
 */
const EXPECTED_CONSOLE_ERROR_SUBSTRINGS = ["Telegram SDK init() failed"];

/**
 * Пункт 3 issue #126 — набор должен ловить не только "экран показал не тот
 * текст", но и "экран упал внутри React без видимого сообщения об ошибке".
 * page.on("pageerror") — необработанные исключения (например, из
 * ErrorBoundary.tsx, если он сам не перехватил), console "error" —
 * warning/error, залогированные кодом приложения или React. Собирается с
 * первого addInitScript/goto, поэтому нужно вызывать ДО page.goto.
 */
export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && !EXPECTED_CONSOLE_ERROR_SUBSTRINGS.some((s) => msg.text().includes(s))) {
      errors.push(msg.text());
    }
  });
  page.on("pageerror", (error) => {
    errors.push(error.message);
  });
  return errors;
}

/**
 * Падение теста на неожиданном 4xx/5xx с /api/* — реальный признак того,
 * что путь, который сценарий должен пройти без ошибок, где-то ответил
 * отказом. allowedStatuses пропускает коды, которые сценарий проверяет
 * НАМЕРЕННО (например 401 у заведомо испорченной подписи) — по умолчанию
 * пусто, обычный сценарий не ждёт вообще никаких ошибок API.
 */
export function collectUnexpectedApiFailures(page: Page, allowedStatuses: number[] = []): string[] {
  const failures: string[] = [];
  page.on("response", (response) => {
    const url = response.url();
    if (!url.includes("/api/")) {
      return;
    }
    if (response.status() >= 400 && !allowedStatuses.includes(response.status())) {
      failures.push(`${response.status()} ${url}`);
    }
  });
  return failures;
}
