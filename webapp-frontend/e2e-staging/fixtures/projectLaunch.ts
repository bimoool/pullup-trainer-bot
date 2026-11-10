import { launchUrl } from "./initData";

/** Explicit browser-profile contract; never infer Telegram's platform from the host OS. */
export function projectLaunchUrl(baseUrl: string, initData: string, projectName: string, version: "8.0" | "6.1" = "8.0"): string {
  if (projectName !== "iphone-webkit" && projectName !== "chromium-mobile") {
    throw new Error(`Unsupported staging browser project: ${projectName}`);
  }
  const platform = projectName === "iphone-webkit" ? "ios" : "android";
  return launchUrl(baseUrl, initData, platform, version);
}
