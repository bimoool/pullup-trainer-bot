// HTTP-клиент входа в браузере (WEB-AUTH). Токен сессии — HttpOnly cookie, из JS не виден; здесь только короткоживущий
// секрет запроса входа (в памяти страницы, не в storage).
import type { PollStatus } from "./webAuthLogic.ts";

export type LoginRequestInfo = {
  request_id: string;
  browser_secret: string;
  code: string;
  expires_in_seconds: number;
  poll_interval_seconds: number;
  bot_link: string | null;
};

export type SessionInfo = { authenticated: boolean; first_name: string | null };

export class RateLimitedError extends Error {}

export async function createLoginRequest(signal?: AbortSignal): Promise<LoginRequestInfo> {
  const response = await fetch("/api/web-auth/login-requests", { method: "POST", signal, credentials: "same-origin" });
  if (response.status === 429) {
    throw new RateLimitedError("rate_limited");
  }
  if (!response.ok) {
    throw new Error(`login request failed: ${response.status}`);
  }
  return (await response.json()) as LoginRequestInfo;
}

export async function pollLoginRequest(requestId: string, secret: string, signal?: AbortSignal): Promise<PollStatus> {
  const response = await fetch(`/api/web-auth/login-requests/${encodeURIComponent(requestId)}/poll`, {
    method: "POST", headers: { "X-Web-Login-Secret": secret }, signal, credentials: "same-origin",
  });
  if (response.status === 429) {
    return "too_many";
  }
  if (response.status === 404) {
    return "not_found";
  }
  if (!response.ok) {
    throw new Error(`poll failed: ${response.status}`);
  }
  const body = (await response.json()) as { status: PollStatus };
  return body.status;
}

export async function fetchSessionInfo(): Promise<SessionInfo> {
  const response = await fetch("/api/web-auth/session", { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(`session check failed: ${response.status}`);
  }
  return (await response.json()) as SessionInfo;
}

export async function logoutRequest(): Promise<void> {
  await fetch("/api/web-auth/logout", {
    method: "POST", headers: { "X-Telegram-Init-Data": "web-session" }, credentials: "same-origin",
  });
}
