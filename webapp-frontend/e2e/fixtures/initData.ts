import { createHmac } from "node:crypto";

/**
 * Подпись initData тем же алгоритмом, что реально проверяет
 * init_data_py.InitData.validate() на бэкенде (app/web/auth.py) — не
 * самописный HMAC "на глаз", а сверено чтением исходника установленной в
 * проекте версии (init-data-py==0.2.7, см. pyproject.toml: ">=0.2.7,<1"):
 * InitData.calculate_hash() строит data_check_string из отсортированных
 * "key=value" (без поля hash), делает `.replace("/", "\\/")` — важно, без
 * этой замены подпись разошлась бы для любого значения, содержащего "/" —
 * и подписывает HMAC-SHA256 ключом, производным от BOT_TOKEN. Тот же
 * алгоритм независимо воспроизведён на Python в
 * tests/test_web/test_auth.py::_sign/_build_init_data (issue #15) — эта
 * функция его TS-аналог для Playwright, не второй источник правды.
 */
function signFields(fields: Record<string, string>, botToken: string): string {
  const dataCheckString = Object.keys(fields)
    .sort()
    .map((key) => `${key}=${fields[key]}`)
    .join("\n")
    .replace(/\//g, "\\/");
  const secretKey = createHmac("sha256", "WebAppData").update(botToken).digest();
  return createHmac("sha256", secretKey).update(dataCheckString).digest("hex");
}

export interface TelegramTestUser {
  id: number;
  firstName: string;
}

/**
 * Собирает и подписывает initData так, как это делает реальный Telegram-
 * клиент — только тестовым BOT_TOKEN, тем же, с которым поднят сервер
 * FastAPI в этом прогоне (см. getTestBotToken ниже). Результат — сырая
 * query-string, ровно то, что webapp-frontend/src/App.tsx кладёт в
 * заголовок X-Telegram-Init-Data (см. api.ts) без дополнительного
 * разбора на клиенте.
 */
export function buildInitData(user: TelegramTestUser, botToken: string): string {
  const fields: Record<string, string> = {
    user: JSON.stringify({ id: user.id, first_name: user.firstName }),
    auth_date: String(Math.floor(Date.now() / 1000)),
    query_id: "AAEAAAAAAAAA",
  };
  fields.hash = signFields(fields, botToken);
  return Object.keys(fields)
    .map((key) => `${key}=${encodeURIComponent(fields[key])}`)
    .join("&");
}

/**
 * BOT_TOKEN должен совпадать с тем, с которым запущен тестовый
 * `uvicorn app.web.main:app` (см. webapp-frontend/e2e/README.md) — иначе
 * get_validated_init_data (app/web/auth.py) отклонит подпись 401-м, как и
 * при реальном рассинхроне секрета между ботом и Mini App.
 */
export function getTestBotToken(): string {
  const token = process.env.BOT_TOKEN;
  if (!token) {
    throw new Error(
      "BOT_TOKEN не задан — E2E подписывает initData тем же токеном, что и тестовый сервер FastAPI " +
        "(см. webapp-frontend/e2e/README.md)",
    );
  }
  return token;
}
