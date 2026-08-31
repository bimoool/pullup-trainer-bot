export interface HelloResponse {
  name: string;
  is_onboarded: boolean;
  readiness_status: string | null;
  days_since_last_workout: number | null;
}

/**
 * Один origin с бэкендом (см. app/web/main.py — та же FastAPI-статика),
 * поэтому относительный путь без CORS. initDataRaw — сырая, не
 * распарсенная на клиенте query-string (см. app/web/auth.py: доверять
 * можно только тому, что бэкенд сам проверил подписью).
 */
export async function fetchHello(initDataRaw: string): Promise<HelloResponse> {
  const response = await fetch("/api/hello", {
    headers: { "X-Telegram-Init-Data": initDataRaw },
  });
  if (!response.ok) {
    throw new Error(`GET /api/hello failed: ${response.status}`);
  }
  return response.json();
}
