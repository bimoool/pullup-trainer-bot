import { test } from "@playwright/test";
import { authedContext, nav, onboardViaUi, Trace } from "./helpers";

// Empty-state matrix, light + dark pass. PROFILE audit_empty_library (tg 7100016 light, 7100017 dark).
for (const [theme, id] of [["light", 7100016], ["dark", 7100017]] as const) {
  test(`Empty states ${theme}`, async ({ browser }, info) => {
    const ctx = await authedContext(browser, id, theme);
    const page = await ctx.newPage();
    const T = new Trace(`EMPTY-${theme}`, page, info);
    await onboardViaUi(T);
    await T.check("E-home catalogue empty", true, "-", "E-home");
    await T.tap("Планы", nav(page, "Планы")); await T.check("E1 no active plan", true, "-", "E1");
    await T.tap("Мои тренировки", page.getByRole("button", { name: "Мои тренировки" })); await T.check("E3 no personal workouts", true, "-", "E3");
    await page.goto("/"); await page.waitForTimeout(1500);
    await T.tap("Журнал", nav(page, "Журнал")); await T.check("E5 no journal", true, "-", "E5");
    await T.tap("Аналитика", nav(page, "Аналитика")); await T.check("E6 no analytics", true, "-", "E6");
    await T.tap("Профиль", nav(page, "Профиль")); await T.check("profile", true, "-", "E-profile");
    await page.goto("/"); await page.waitForTimeout(1500);
    await T.tap("Тесты", page.getByRole("button", { name: /^Тесты/ }));
    await T.tap("Максимум подтягиваний", page.getByText("Максимум подтягиваний").first()); await T.check("E7 no assessment results", true, "-", "E7");
    await page.goto("/"); await page.waitForTimeout(1500);
    await T.tap("Баннер: собрать свой комплекс", page.getByRole("button", { name: "Баннер: собрать свой комплекс" }));
    await page.getByPlaceholder("Например, 3 минуты подтягиваний").fill("Пустая");
    await T.tap("Создать и добавить упражнения", page.getByRole("button", { name: "Создать и добавить упражнения" }));
    await T.check("E12 custom workout with zero exercises (editor)", true, "-", "E12-editor");
    await T.tap("+ Добавить упражнение", page.getByRole("button", { name: "+ Добавить упражнение" })); await T.check("E4 empty library picker", true, "-", "E4");
    await page.getByRole("searchbox").fill("zzz"); await page.waitForTimeout(800); await T.check("E4b no matching exercise", true, "-", "E4b");
    await page.goto("/"); await page.waitForTimeout(1500);
    await T.tap("Мои тренировки card", page.getByRole("button", { name: /Пустая/ })); await T.check("E12 detail (disabled Начать)", true, "-", "E12-detail");
    T.finish();
  });
}
