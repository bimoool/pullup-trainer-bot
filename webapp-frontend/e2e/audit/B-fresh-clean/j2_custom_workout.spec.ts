import { test } from "@playwright/test";
import { authedContext, uid, nav, onboardViaUi, Trace } from "./helpers";

// J2 + J3 + J7. PROFILE audit_empty_library (tg 7100012). S0: clean install; new user; no exercises, no workouts, no plan.
test("J2/J3/J7 custom workout from nothing -> run -> journal -> analytics -> plan", async ({ browser }, info) => {
  const ctx = await authedContext(browser, uid(12));
  const page = await ctx.newPage();
  const T = new Trace("J2", page, info);
  await onboardViaUi(T, "10");

  await T.tap("Баннер: собрать свой комплекс", page.getByRole("button", { name: "Баннер: собрать свой комплекс" }));
  await page.getByPlaceholder("Например, 3 минуты подтягиваний").fill("Мои подтягивания");
  await T.tap("Создать и добавить упражнения", page.getByRole("button", { name: "Создать и добавить упражнения" }));
  await T.check("Editor 'Редактировать тренировку' with empty list and a way forward", await page.getByText("Пока пусто. Добавьте первое упражнение").isVisible(), "UNFILED", "editor-empty");
  await T.tap("+ Добавить упражнение", page.getByRole("button", { name: "+ Добавить упражнение" }));
  const emptyPicker = await page.getByText("Ничего не найдено").isVisible();
  const createVisibleWithoutTyping = await page.getByRole("button", { name: /Создать своё/ }).isVisible();
  await T.check("Exercise picker on empty library offers a visible 'create exercise' CTA without typing", !emptyPicker || createVisibleWithoutTyping, "F-B-FRESH-CLEAN-04 (CTA only after typing; hint text only)", "picker-empty");
  await page.getByRole("searchbox").fill("Подтягивания"); await page.waitForTimeout(900);
  await T.tap("Создать своё: «Подтягивания»", page.getByRole("button", { name: /Создать своё/ }));
  await T.check("Protocol screen (type/sets/reps/rest)", await page.getByText("ТИП РАБОТЫ").isVisible(), "F-B-FRESH-CLEAN-04", "protocol");
  await T.tap("Добавить", page.getByRole("button", { name: "Добавить", exact: true }));
  await T.tap("Сохранить", page.getByRole("button", { name: "Сохранить" }));
  await T.check("Workout detail with 1 exercise, 3 × 10", await page.getByText("3 × 10 повторений").isVisible(), "UNFILED", "detail");
  await T.reload("after save"); 
  await T.check("Home 'Мои тренировки' lists the workout after reload", await page.getByText("1 упражнение · 3 × 10").isVisible(), "UNFILED", "home-after-reload");

  // J3: direct start (free workout without plan)
  await T.tap("workout card", page.getByRole("button", { name: /Мои подтягивания 1 упражнение/ }));
  await T.tap("Начать", page.getByRole("button", { name: "Начать" }));
  await T.check("Live ready screen", await page.getByText("ГОТОВЫ К СТАРТУ").isVisible(), "UNFILED", "live-ready");
  await T.tap("Начать (live)", page.getByRole("button", { name: "Начать" }));
  await T.tap("Готов", page.getByRole("button", { name: "Готов" }));
  await page.getByLabel("Повторений").fill("8"); await T.tap("Готово (8)", page.getByRole("button", { name: "Готово" }));
  await T.check("Rest phase with 'Подход 1: 8 повт.'", await page.getByText("Подход 1: 8 повт.").isVisible(), "UNFILED", "live-rest");
  await T.reload("mid-session (J7)");
  await T.check("Live session resumes after reload (rest)", await page.getByText("ЖИВАЯ ТРЕНИРОВКА").isVisible(), "UNFILED", "live-resume");
  await T.tap("Пропустить отдых", page.getByRole("button", { name: "Пропустить отдых" }));
  await T.tap("Готов", page.getByRole("button", { name: "Готов" }));
  await page.getByLabel("Повторений").fill("6"); await T.tap("Готово (6)", page.getByRole("button", { name: "Готово" }));
  await T.tap("Завершить", page.getByRole("button", { name: "Завершить" }).first());
  await T.tap("3 Средне", page.getByRole("button", { name: /3 Средне/ }));
  await T.tap("Сохранить и завершить", page.getByRole("button", { name: "Сохранить и завершить" }));
  await T.check("Summary 'Тренировка завершена' with sets 8 and 6", await page.getByText("Подход 2: 6 повт.").isVisible(), "UNFILED", "summary");
  await T.reload("after summary");
  await T.tap("Журнал", nav(page, "Журнал"));
  await T.check("Журнал shows the workout (Свободная, 2 sets, 14 reps)", await page.getByText("Свободная").isVisible(), "UNFILED", "journal");
  await T.tap("Аналитика", nav(page, "Аналитика"));
  await T.check("Аналитика: 1 тренировка, 14 повторений", await page.getByText("Всего повторений").isVisible() && await page.getByText("14").first().isVisible(), "UNFILED", "analytics");

  // J7: new context, same initData
  const ctx2 = await authedContext(browser, uid(12));
  const p2 = await ctx2.newPage(); const T2 = new Trace("J2", p2, info);
  await p2.goto("/"); await p2.waitForTimeout(2500); T2.log("REOPEN in new context, same initData");
  await T2.tap("Журнал", nav(p2, "Журнал"));
  await T2.check("Журнал still has the workout in a fresh context (J7)", await p2.getByText("Свободная").isVisible(), "UNFILED", "journal-new-ctx");

  // J2b: add to plan from nothing
  await T2.tap("Планы", nav(p2, "Планы"));
  await T2.tap("Мои тренировки", p2.getByRole("button", { name: "Мои тренировки" }));
  await T2.tap("Добавить в план", p2.getByRole("button", { name: "Добавить в план" }));
  await T2.tap("Ср", p2.getByRole("button", { name: "Ср", exact: true }));
  await T2.tap("Добавить", p2.getByRole("button", { name: "Добавить", exact: true }));
  await T2.reload("after add-to-plan");
  await T2.tap("Планы", nav(p2, "Планы"));
  await T2.check("Планы current week shows the added workout (Среда)", await p2.getByText("СРЕДА").isVisible(), "F-B-FRESH-CLEAN-03 (first add-to-plan when no plan exists is silently lost)", "plan-after-add");
  // retry: second add works
  await T2.tap("Мои тренировки", p2.getByRole("button", { name: "Мои тренировки" }));
  await T2.tap("Добавить в план (retry)", p2.getByRole("button", { name: "Добавить в план" }));
  await T2.tap("Чт", p2.getByRole("button", { name: "Чт", exact: true }));
  await T2.tap("Добавить", p2.getByRole("button", { name: "Добавить", exact: true }));
  await T2.reload("after 2nd add"); await T2.tap("Планы", nav(p2, "Планы"));
  await T2.check("Планы shows the workout under ЧЕТВЕРГ after the 2nd add", await p2.getByText("ЧЕТВЕРГ").isVisible(), "F-B-FRESH-CLEAN-03", "plan-after-add2");
  await T2.tap("Начать (plan)", p2.getByRole("button", { name: /^Начать: Мои подтягивания/ }));
  await T2.tap("Начать", p2.getByRole("button", { name: "Начать" }));
  await T2.tap("Готов", p2.getByRole("button", { name: "Готов" }));
  await p2.getByLabel("Повторений").fill("9"); await T2.tap("Готово (9)", p2.getByRole("button", { name: "Готово" }));
  await T2.tap("Пропустить отдых", p2.getByRole("button", { name: "Пропустить отдых" }));
  await T2.tap("Готов", p2.getByRole("button", { name: "Готов" }));
  await p2.getByLabel("Повторений").fill("7"); await T2.tap("Готово (7)", p2.getByRole("button", { name: "Готово" }));
  await T2.tap("Завершить", p2.getByRole("button", { name: "Завершить" }).first());
  await T2.tap("4 Тяжело", p2.getByRole("button", { name: /4 Тяжело/ }));
  await T2.tap("Сохранить и завершить", p2.getByRole("button", { name: "Сохранить и завершить" }));
  await T2.check("Summary after plan start", await p2.getByText("Тренировка завершена").isVisible(), "UNFILED", "summary-plan");
  await T2.tap("Закрыть", p2.getByRole("button", { name: "Закрыть" }));
  await T2.reload(); await T2.tap("Планы", nav(p2, "Планы"));
  await T2.check("Планы shows 1/1 for the week item after completion", await p2.getByText(/1 из 1/).isVisible(), "UNFILED", "plan-done");
  await T2.tap("Журнал", nav(p2, "Журнал"));
  await T2.check("Журнал shows 'По плану' entry", await p2.getByText("По плану").isVisible(), "UNFILED", "journal-plan");
  // remove from plan: template + history must survive unchanged
  await T2.tap("Планы", nav(p2, "Планы"));
  await T2.tap("Действия", p2.getByRole("button", { name: /^Действия: Мои подтягивания/ }));
  await T2.tap("Убрать из плана", p2.getByRole("button", { name: "Убрать из плана" }));
  await T2.tap("Убрать", p2.getByRole("button", { name: "Убрать", exact: true }));
  await T2.reload(); await T2.tap("Журнал", nav(p2, "Журнал"));
  const titles = (await p2.locator("body").innerText());
  await T2.check("Журнал still names the plan-run entry 'Мои подтягивания' after the plan row was removed", (titles.match(/Мои подтягивания/g) ?? []).length >= 2, "F-B-FRESH-CLEAN-06", "journal-after-remove");
  T.failures.push(...T2.failures); T.finish();
});
