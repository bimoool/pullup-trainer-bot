import { test } from "@playwright/test";
import { execSync } from "node:child_process";
import { authedContext, uid, nav, onboardViaUi, Trace } from "./helpers";

// J6 expired. PROFILE audit_fresh_expired (tg 7100015).
// TEST HARNESS INJECTION / DOMAIN NECESSITY: after failure-free UI onboarding (trial), the trial end is moved into the past
// by UPDATE users SET subscription_expires_at = now() - 1 day (SubscriptionService.refresh_status then flips the cache to EXPIRED lazily).
test("J6 expired user", async ({ browser }, info) => {
  const ctx = await authedContext(browser, uid(15));
  const page = await ctx.newPage();
  const T = new Trace("J6", page, info);
  await onboardViaUi(T);
  T.log(`TEST HARNESS INJECTION: UPDATE users SET subscription_expires_at=now()-interval '1 day' WHERE telegram_id=${uid(15)}`);
  execSync(`PGPASSWORD=pullup psql -h localhost -U pullup pullup_audit_b -c "UPDATE users SET subscription_expires_at=now()-interval '1 day' WHERE telegram_id=${uid(15)}"`);
  await T.reload("after expiry injection");
  await T.tap("Профиль", nav(page, "Профиль"));
  await T.tap("Подписка", page.getByRole("button", { name: /^Подписка/ }));
  await T.check("Subscription screen says expired (not 'пробный период') right after expiry", await page.getByText("истекла").isVisible(), "F-B-FRESH-CLEAN-08 (stale subscription cache label)", "expired-subscription");
  await T.check("Subscription screen offers a way to pay", await page.getByRole("button", { name: /Оплатить|Продлить/ }).isVisible(), "F-B-FRESH-CLEAN-05 (paywall)", "expired-subscription-pay");
  for (const tab of ["Главная", "Планы", "Журнал", "Аналитика"]) {
    await page.goto("/"); await page.waitForTimeout(1500);
    await T.tap(tab, nav(page, tab));
    await T.check(`${tab}: paywall / no_access explanation visible for expired user`, await page.getByText(/подписк|доступ/i).first().isVisible(), "F-B-FRESH-CLEAN-05", `expired-${tab}`);
  }
  await page.goto("/"); await page.waitForTimeout(1500);
  await T.tap("Баннер: собрать свой комплекс", page.getByRole("button", { name: "Баннер: собрать свой комплекс" }));
  await T.check("Expired user can still create a workout (no gate)", await page.getByText("Новая тренировка").isVisible(), "F-B-FRESH-CLEAN-05");
  T.finish();
});
