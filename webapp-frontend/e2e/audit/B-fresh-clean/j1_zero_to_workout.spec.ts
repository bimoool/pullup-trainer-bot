import { test } from "@playwright/test";
import { authedContext, nav, onboardViaUi, Trace } from "./helpers";

// J1 Zero-to-Workout. PROFILE audit_fresh_active (tg 7100011). S0: pure clean install (alembic head only), new Telegram user.
test("J1 zero-to-workout: discover a program -> start", async ({ browser }, info) => {
  const ctx = await authedContext(browser, 7100011);
  const page = await ctx.newPage();
  const T = new Trace("J1", page, info);
  await onboardViaUi(T);

  T.log("OPEN Home -> look for a program to discover");
  const catalogEmpty = await page.getByText("Каталог курсов появится здесь позже.").isVisible();
  await T.check("Home shows >=1 program card in the catalogue", !catalogEmpty, "F-B-FRESH-CLEAN-01 (empty catalogue)", "home-catalogue");

  await T.tap("Планы", nav(page, "Планы"));
  await T.check("Планы: active plan, current week, >=1 workout", !(await page.getByText("Курсов в плане нет").isVisible()), "F-B-FRESH-CLEAN-02", "plans-empty");
  await T.tap("Выбрать курс на Главной", page.getByRole("button", { name: "Выбрать курс на Главной" }));
  const backOnHomeDeadEnd = await page.getByText("Каталог курсов появится здесь позже.").isVisible();
  await T.check("CTA 'Выбрать курс на Главной' leads to a course to choose", !backOnHomeDeadEnd, "F-B-FRESH-CLEAN-02", "cta-loop-home");

  await T.tap("Баннер: открыть план дня", page.getByRole("button", { name: "Баннер: открыть план дня" }));
  await T.check("'Откройте план дня' opens a day plan with a workout", !(await page.getByText("Курсов в плане нет").isVisible()), "F-B-FRESH-CLEAN-02", "plan-of-day-loop");
  await T.reload("after dead-end loop");
  T.log("J1 steps 4..N (Program Detail, add program, Start, Live, Finish, Журнал, Аналитика, reopen): BLOCKED BY F-B-FRESH-CLEAN-01");
  T.finish();
});
