import type { Page } from "@playwright/test";

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
    if (msg.type() === "error") {
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
