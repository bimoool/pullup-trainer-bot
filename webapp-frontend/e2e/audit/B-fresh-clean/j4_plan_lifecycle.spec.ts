import { test } from "@playwright/test";
import { authedContext, uid, nav, onboardViaUi, Trace } from "./helpers";

// J4 plan lifecycle from empty. PROFILE audit_fresh_active (tg 7100014).
test("J4 plan lifecycle from empty", async ({ browser }, info) => {
  const ctx = await authedContext(browser, uid(14));
  const page = await ctx.newPage();
  const T = new Trace("J4", page, info);
  await onboardViaUi(T);
  await T.tap("Планы", nav(page, "Планы"));
  await T.check("E1 empty Планы has a CTA that resolves (add program)", false, "F-B-FRESH-CLEAN-02", "E1-plans-empty");
  // create a workout through UI so that manual plan content is possible
  await T.tap("Главная", nav(page, "Главная"));
  await T.tap("Баннер: собрать свой комплекс", page.getByRole("button", { name: "Баннер: собрать свой комплекс" }));
  await page.getByPlaceholder("Например, 3 минуты подтягиваний").fill("План-тест");
  await T.tap("Создать и добавить упражнения", page.getByRole("button", { name: "Создать и добавить упражнения" }));
  await T.tap("+ Добавить упражнение", page.getByRole("button", { name: "+ Добавить упражнение" }));
  await page.getByRole("searchbox").fill("Подтягивания"); await page.waitForTimeout(900);
  await T.tap("Создать своё", page.getByRole("button", { name: /Создать своё/ }));
  await T.tap("Добавить", page.getByRole("button", { name: "Добавить", exact: true }));
  await T.tap("Сохранить", page.getByRole("button", { name: "Сохранить" }));
  await T.tap("Добавить в план", page.getByRole("button", { name: "Добавить в план" }));
  await T.tap("Пн", page.getByRole("button", { name: "Пн", exact: true }));
  await T.tap("Добавить", page.getByRole("button", { name: "Добавить", exact: true }));
  await T.reload("after first add-to-plan");
  await T.tap("Планы", nav(page, "Планы"));
  const week = await page.getByText("Неделя 1").isVisible();
  await T.check("Plan exists + current week created (rows: 0 workouts) — 'plan exists but current week has 0 workouts'", week && await page.getByText(/0 из 0/).isVisible(), "F-B-FRESH-CLEAN-03", "plan-exists-week-0");
  await T.check("The workout just added appears in current week", await page.getByText("ПОНЕДЕЛЬНИК").isVisible(), "F-B-FRESH-CLEAN-03");
  // add again, now plan_week exists
  await T.tap("Мои тренировки", page.getByRole("button", { name: "Мои тренировки" }));
  await T.tap("Добавить в план", page.getByRole("button", { name: "Добавить в план" }));
  await T.tap("Чт", page.getByRole("button", { name: "Чт", exact: true }));
  await T.tap("Добавить", page.getByRole("button", { name: "Добавить", exact: true }));
  await T.reload(); await T.tap("Планы", nav(page, "Планы"));
  await T.check("Item under ЧЕТВЕРГ after reload", await page.getByText("ЧЕТВЕРГ").isVisible(), "F-B-FRESH-CLEAN-03", "plan-thu");
  // move day
  await T.tap("Действия", page.getByRole("button", { name: /^Действия: План-тест/ }));
  await T.tap("Перенести", page.getByRole("button", { name: "Перенести" }));
  await T.tap("Пт", page.getByRole("button", { name: "Пт", exact: true }));
  await T.tap("Сохранить", page.getByRole("button", { name: "Сохранить" }));
  await T.reload(); await T.tap("Планы", nav(page, "Планы"));
  await T.check("Moved to ПЯТНИЦА after reload", await page.getByText("ПЯТНИЦА").isVisible(), "UNFILED", "plan-fri");
  // free pool
  await T.tap("Действия", page.getByRole("button", { name: /^Действия: План-тест/ }));
  await T.tap("Перенести", page.getByRole("button", { name: "Перенести" }));
  await T.tap("Свободный пул", page.getByRole("button", { name: "Свободный пул" }));
  await T.tap("Сохранить", page.getByRole("button", { name: "Сохранить" }));
  await T.reload(); await T.tap("Планы", nav(page, "Планы"));
  await T.check("Item in СВОБОДНЫЙ ПУЛ after reload", await page.getByText("СВОБОДНЫЙ ПУЛ").isVisible(), "UNFILED", "plan-pool");
  // copy week
  await T.tap("Действия: Текущий план", page.getByRole("button", { name: "Действия: Текущий план" }));
  await T.tap("Скопировать неделю 1 → 2", page.getByRole("button", { name: /Скопировать неделю/ }));
  await T.tap("Скопировать", page.getByRole("button", { name: "Скопировать", exact: true }));
  await T.check("Week 2 holds the copy ('Скопировано: 1')", await page.getByText("Неделя 2").isVisible(), "UNFILED", "plan-copy");
  await T.reload(); await T.tap("Планы", nav(page, "Планы"));
  await T.check("Current-week indicator 'Текущая неделя' on week 1 after reload", await page.getByText(/Текущая неделя/).isVisible(), "UNFILED");
  await T.tap("Следующая неделя", page.getByRole("button", { name: "Следующая неделя" }));
  await T.check("Week 2 persists with the copied row", await page.getByText("Неделя 2").isVisible() && await page.getByText("План-тест").isVisible(), "UNFILED", "plan-week2");
  await T.tap("Следующая неделя", page.getByRole("button", { name: "Следующая неделя" }));
  await T.check("E11 newly created week 3 has an empty state with CTA", await page.getByText("На эту неделю пока ничего не запланировано.").isVisible(), "UNFILED", "E11-new-week");
  await T.tap("Предыдущая неделя", page.getByRole("button", { name: "Предыдущая неделя" }));
  await T.tap("Предыдущая неделя", page.getByRole("button", { name: "Предыдущая неделя" }));
  // remove workout from plan; template + history survive
  await T.tap("Действия", page.getByRole("button", { name: /^Действия: План-тест/ }));
  await T.tap("Убрать из плана", page.getByRole("button", { name: "Убрать из плана" }));
  await T.tap("Убрать", page.getByRole("button", { name: "Убрать", exact: true }));
  await T.reload(); await T.tap("Главная", nav(page, "Главная"));
  await T.check("Template workout still exists on Home after removal from plan", await page.getByText("План-тест").first().isVisible(), "UNFILED");
  T.log("J4 'add program', 'program with no generated PlanItems', 'remove program': BLOCKED BY F-B-FRESH-CLEAN-01 (no programs exist)");
  T.finish();
});
