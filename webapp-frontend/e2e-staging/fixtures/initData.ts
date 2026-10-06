import { createHmac } from "node:crypto";

/**
 * Same algorithm as the real Telegram client and as the app's validator (app/web/auth.py ->
 * init_data_py.InitData.validate): HMAC-SHA256 over the sorted "key=value" lines, key =
 * HMAC("WebAppData", bot_token), with "/" escaped as "\/" (init_data_py quirk). Mirrors
 * scripts/qa/mint_init_data.py, whose output is proven against the app validator in
 * tests/test_web/test_qa_mint_init_data.py.
 *
 * The token comes ONLY from STAGING_BOT_TOKEN and is never logged or attached to artifacts.
 */
export const QA_IDENTITIES = {
  qa_fresh_active: 7_000_000_001,
  qa_aged_active: 7_000_000_002,
  qa_expired: 7_000_000_003,
  qa_legacy_or_partial: 7_000_000_004,
  qa_aged_legacy_snapshot: 7_000_000_005,
} as const;
export type QaIdentity = keyof typeof QA_IDENTITIES;

function sign(fields: Record<string, string>, botToken: string): string {
  const dataCheckString = Object.keys(fields)
    .sort()
    .map((k) => `${k}=${fields[k]}`)
    .join("\n")
    .replace(/\//g, "\\/");
  const secret = createHmac("sha256", "WebAppData").update(botToken).digest();
  return createHmac("sha256", secret).update(dataCheckString).digest("hex");
}

export function stagingBotToken(): string {
  const token = process.env.STAGING_BOT_TOKEN;
  if (!token) {
    // Deliberately no hint about the value; only the name of the variable.
    throw new Error("STAGING_BOT_TOKEN is not set (GitHub secret / server env); needed to sign QA initData");
  }
  return token;
}

export function buildInitData(telegramId: number, botToken: string, authDate: number = Math.floor(Date.now() / 1000)): string {
  const fields: Record<string, string> = {
    user: JSON.stringify({ id: telegramId, first_name: "QA" }),
    auth_date: String(authDate),
    query_id: "AAEAAAAAAAAA",
    // Real clients send an Ed25519 `signature`; the app does not verify it but the frontend SDK requires the
    // field. Placeholder, covered by the HMAC hash (same as scripts/qa/mint_init_data.py).
    signature: "QA" + "A".repeat(84),
  };
  fields.hash = sign(fields, botToken);
  return Object.keys(fields)
    .map((k) => `${k}=${encodeURIComponent(fields[k])}`)
    .join("&");
}

/**
 * The URL Telegram opens a Mini App with: launch parameters travel in the location HASH
 * (tgWebAppData / tgWebAppVersion / tgWebAppPlatform / tgWebAppThemeParams). The frontend reads them
 * through retrieveLaunchParams() (App.tsx) exactly as in a real client; nothing is stubbed.
 */
export function launchUrl(baseUrl: string, initData: string, platform: "ios" | "android" | "tdesktop" = "ios"): string {
  const params = new URLSearchParams({
    tgWebAppData: initData,
    tgWebAppVersion: "8.0",
    tgWebAppPlatform: platform,
    tgWebAppThemeParams: JSON.stringify({
      bg_color: "#ffffff", text_color: "#000000", hint_color: "#707579", link_color: "#2481cc",
      button_color: "#2481cc", button_text_color: "#ffffff", secondary_bg_color: "#efeff4",
    }),
  });
  return `${baseUrl.replace(/\/+$/, "")}/#${params.toString()}`;
}
