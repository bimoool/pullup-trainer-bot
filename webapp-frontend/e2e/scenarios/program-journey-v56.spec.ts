import { expect, test, type Page } from "@playwright/test";

import { answerChecksV2, noWakeLock } from "../fixtures/builderFlow";
import { buildInitData, getTestBotToken } from "../fixtures/initData";
import { openAppAs } from "../fixtures/setup";

/**
 * MVP: основная программа «Подтягивания» V5.6 (docs/domain/PULLUPS_V5_6.md) на СВЕЖЕМ обычном профиле — без сидов
 * пользователя и без админ-прав (telegram id вне ADMIN_IDS): онбординг → замер → подключение программы → назначение
 * → тренировка A → итог → Журнал → следующая тренировка. Числа — из контракта:
 *   M = 8 (< 10) → уровень 1 (с помощью); R = 10 → A: a = min(20, max(3, ⌊0,7·10⌋)) = 7 → «7/7/7/7+», отдых 240 с;
 *   объём → сила 900 с; сила уровня 1 «5/5/5/5/5–8», отдых 180 с; 2 основных занятия в неделю; A/B по очереди.
 *   Факт A 7/7/7/9 (AMRAP ≥ p4 + 2, техника «Да») → зелёный: +1 в подход с наименьшей целью → «8/7/7/7+».
 *   V_ref = 7+7+7+9 = 30 → B: S = min(20, max(10, ⌊30/5⌋+1)) = 10, q = 5 → «10×5», отдых 30 с.
 *   Пятый подход силы 6 (5–7) → помощь та же.
 * Между основными занятиями — минимальный отдых 3 дня (`main_min_days_between_starts`): «Доступно с …» или, если
 *   это за пределами недели, «Не успеть на этой неделе».
 *
 * Тренировку B сегодня начать нельзя (тот самый отдых). Второй тест — только локально и по явному запросу:
 * продолжает пользователя первого прогона (`E2E_JOURNEY_TG`) после того, как прошедшие 3 дня смоделированы в
 * локальной e2e-БД (performed_at занятия A сдвинут назад). Правила продукта не меняются; без переменной — пропуск.
 */
test.describe.configure({ mode: "serial" });
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
test.setTimeout(180_000);

const CONTINUE_TG = process.env.E2E_JOURNEY_TG ? Number(process.env.E2E_JOURNEY_TG) : null;
const TG = CONTINUE_TG ?? 7_700_000 + Math.floor(Math.random() * 90_000);  // не в ADMIN_IDS, новый на каждый прогон
let inclusionId: number | null = null;

async function api(page: Page, path: string) {
  const response = await page.request.get(path, {
    headers: { "X-Telegram-Init-Data": buildInitData({ id: TG, firstName: "E2E" }, getTestBotToken()) },
  });
  expect(response.ok(), `${path} → ${response.status()}`).toBe(true);
  return response.json();
}

async function onboard(page: Page) {
  await expect(page.getByText("Сколько подтягиваний вышло?")).toBeVisible();
  await page.getByLabel("Сколько подтягиваний вышло?").fill("8");
  await page.getByRole("button", { name: "Далее" }).click();
  await expect(page.getByText("Записал: 8 повторений. Всё верно?")).toBeVisible();
  await page.getByRole("button", { name: "Да" }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByLabel("Твой вес в кг?").fill("78");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Рост в см?").fill("180");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Пол").selectOption({ label: "Мужской" });
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Дата рождения").fill("1992-04-15");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Часовой пояс").selectOption({ label: "Москва (UTC+3)" });
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();
}

/** Подход за подходом: цель на экране, ввод, подтверждение; после подхода — отдых ровно по рецепту. */
async function playSets(page: Page, sets: { target: string; value: string; restAfter: RegExp | null; exercise: string }[]) {
  const phase = page.getByTestId("engine-phase");
  for (const set of sets) {
    await expect(phase).toHaveText(/Приготовься|Отдых|Пошёл/);
    if ((await phase.textContent())?.trim() !== "Пошёл") {
      await page.getByTestId("engine-skip").click();
    }
    await expect(phase).toHaveText("Пошёл");
    await expect(page.locator(".live-exercise")).toHaveText(set.exercise);
    await expect(page.getByTestId("engine-target")).toHaveText(set.target);
    await page.getByLabel("Результат подхода").fill(set.value);
    await page.getByTestId("engine-submit").click();
    if (set.restAfter !== null) {
      await expect(phase).toHaveText("Отдых");
      await expect(page.getByTestId("engine-timer")).toHaveText(set.restAfter);
    } else {
      await expect(phase).not.toHaveText("Пошёл");
    }
    await expect(page.getByTestId("engine-saving")).toHaveCount(0);
  }
}

const rest = (minutes: number) => new RegExp(`^(${minutes}:00|${minutes - 1}:5\\d)$`);
const REST_30 = /^(0:30|0:2\d)$/;

test("V5.6 на свежем профиле: онбординг → программа → A по рецепту → итог → Журнал → прогрессия и следующая B", async ({ page }) => {
  test.skip(CONTINUE_TG !== null, "продолжение прогона: первая часть уже пройдена этим пользователем");
  console.log(`journey TG=${TG}`);
  const { consoleErrors, apiFailures } = await openAppAs(page, TG);
  await onboard(page);

  // Подключение программы.
  await page.getByRole("button", { name: /^Подтягивания/ }).first().click();
  await expect(page.getByText("Основные тренировки — 2 раза в неделю (A и B по очереди", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await expect(page.getByRole("button", { name: "В плане" })).toBeVisible();

  // Назначение: 2 основных занятия на этой неделе.
  await page.reload();
  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByTestId("plan-week-progress").first()).toHaveText(/Текущая неделя · 0 из 2/);
  await expect(page.getByRole("button", { name: /^Начать: Подтягивания/ })).toHaveCount(2);

  // Недостающие входы (M < 10 → уровень 1): ничего не угадывается.
  await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
  await expect(page.getByTestId("course-setup-required")).toContainText("начинается с помощью");
  await page.getByTestId("course-input-volume_capacity").fill("10");
  await page.getByTestId("course-volume-band-name").fill("Синяя");
  await page.getByTestId("course-volume-band-colour").fill("синяя");
  await page.getByTestId("course-volume-band-attachment").fill("петля на перекладине");
  await page.getByTestId("course-volume-band-position").fill("стопа");
  await page.getByTestId("course-strength-band-bodyweight").check();
  await page.getByTestId("course-setup-save").click();
  await expect(page.getByText("Блок 1: 7/7/7/7+")).toBeVisible();
  await expect(page.getByText("Блок 2: 5/5/5/5/5–8")).toBeVisible();

  const started = page.waitForResponse((r) => /\/api\/v2\/sessions\/live$/.test(r.url()) && r.status() === 200);
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await started;
  const planItems = (await api(page, "/api/v2/plan")).plan.plan_items as { program_inclusion_id: number | null }[];
  inclusionId = planItems.find((item) => item.program_inclusion_id !== null)?.program_inclusion_id ?? null;
  expect(inclusionId).not.toBeNull();

  // Тренировка A: объём 7/7/7/7+ (отдых 4:00), 15:00 до силы, сила 5/5/5/5/5–8 (отдых 3:00).
  const A = "Подтягивания — объём";
  const S = "Подтягивания — сила";
  await playSets(page, [
    { exercise: A, target: "Подход 1/4 · Цель: 7 повт.", value: "7", restAfter: rest(4) },
    { exercise: A, target: "Подход 2/4 · Цель: 7 повт.", value: "7", restAfter: rest(4) },
    { exercise: A, target: "Подход 3/4 · Цель: 7 повт.", value: "7", restAfter: rest(4) },
    { exercise: A, target: "Попытка 4/4 · Минимум 7 повт. (AMRAP)", value: "9", restAfter: rest(15) },
    { exercise: S, target: "Подход 1/5 · Цель: 5 повт.", value: "5", restAfter: rest(3) },
    { exercise: S, target: "Подход 2/5 · Цель: 5 повт.", value: "5", restAfter: rest(3) },
    { exercise: S, target: "Подход 3/5 · Цель: 5 повт.", value: "5", restAfter: rest(3) },
    { exercise: S, target: "Подход 4/5 · Цель: 5 повт.", value: "5", restAfter: rest(3) },
    { exercise: S, target: "Подход 5/5 · Цель: 5–8 повт. (потолок 8)", value: "6", restAfter: null },
  ]);

  // Техника и отдых по блокам — с лимитами рецепта; «Да» по всем.
  await expect(page.getByTestId("engine-confirm")).toContainText("Отдых не дольше 4:00");
  await expect(page.getByTestId("engine-confirm")).toContainText("Отдых не дольше 3:00");
  await answerChecksV2(page, "valid");
  const confirmed = page.waitForResponse((r) => r.url().includes("/events") && r.status() === 200
    && (r.request().postData() ?? "").includes("confirm_blocks"));
  await page.getByTestId("engine-confirm-submit").click();
  const progression = (await (await confirmed).json()).course_progression;
  expect(progression.next_workout_role).toBe("B");
  await expect(page.getByTestId("engine-complete")).toBeVisible();
  await page.getByTestId("engine-save").click();

  // Итог.
  await expect(page.getByTestId("course-progression")).toContainText("Следующая тренировка B");
  await page.getByRole("button", { name: "Закрыть" }).click();

  // Журнал: план и факт обоих блоков.
  await page.getByRole("button", { name: "Журнал", exact: true }).click();
  await page.locator(".history-card").filter({ hasText: "Подтягивания" }).first().click();
  await page.getByTestId("journal-sheet-open").click();
  for (const line of ["Объём A", "План: 7 · 7 · 7 · 7", "Факт: 7 · 7 · 7 · 9", "Сила с помощью", "План: 5 · 5 · 5 · 5 · 5", "Факт: 5 · 5 · 5 · 5 · 6"]) {
    await expect(page.getByText(line, { exact: true })).toBeVisible();
  }

  // Состояние программы на сервере: прогрессия A и рецепт следующей B.
  const course = await api(page, `/api/v2/program-inclusions/${inclusionId}/course`);
  expect(course.next_workout_role).toBe("B");
  expect(course.state.volume_a.targets).toEqual([8, 7, 7, 7]);
  expect(course.state.strength_a.assistance.kind).toBe("bodyweight");
  const [bVolume, bStrength] = course.next_workout.blocks;
  expect(bVolume.block_role).toBe("b_volume");
  expect(bVolume.sets.map((s: { target_reps: number }) => s.target_reps)).toEqual(Array(10).fill(5));
  expect(bVolume.sets.slice(0, 9).every((s: { rest_after_seconds: number }) => s.rest_after_seconds === 30)).toBe(true);
  expect(bStrength.block_role).toBe("assisted_strength");
  expect(bStrength.sets.map((s: { marker: string }) => s.marker)).toEqual(["working", "working", "working", "working", "control"]);

  // Следующая тренировка: занятие засчитано, следующее — только после минимального отдыха (3 дня).
  await page.reload();
  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByTestId("plan-week-progress").first()).toHaveText(/Текущая неделя · 1 из 2/);
  await expect(page.getByText("Ещё рано для следующей тренировки", { exact: false })).toBeVisible();
  // Отдых 3 дня от сегодняшнего старта (пояс пользователя — Москва): попадает в эту неделю — «Доступно с <день>»,
  // за воскресенье — «Не успеть на этой неделе» (PROGRAM_PLAN §4, J11). Ожидание считается от даты, а не от дня недели
  // прогона (CI 16.10, пятница: следующая — понедельник уже другой недели).
  const moscow = new Date(new Date().toLocaleString("en-US", { timeZone: "Europe/Moscow" }));
  const daysToSunday = (7 - moscow.getDay()) % 7;
  const available = new Date(moscow.getFullYear(), moscow.getMonth(), moscow.getDate() + 3);
  const nextWeek = 3 > daysToSunday;
  await expect(page.getByText(nextWeek ? "Не успеть на этой неделе" : `Доступно с ${available.getDate()} `, { exact: false })).toBeVisible();
  if (nextWeek) {
    // Строка «Не успеть на этой неделе» сохраняет кнопку «Начать», но старт раньше отдыха всё равно отказан:
    // пред-экран объясняет, с какого дня можно (правило отдыха не обходится).
    await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
    await expect(page.getByTestId("pre-screen-too-early")).toContainText(`доступна с ${available.getDate()} `);
    await expect(page.getByRole("button", { name: "Начать", exact: true })).toHaveCount(0);
  } else {
    await expect(page.getByRole("button", { name: /^Начать: Подтягивания/ })).toHaveCount(0);
  }

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("V5.6 следующая тренировка B исполняется по рецепту и двигает свою прогрессию (локально, после смоделированных 3 дней)", async ({ page }) => {
  test.skip(CONTINUE_TG === null, "только локально: E2E_JOURNEY_TG + смоделированные 3 дня отдыха");
  const { consoleErrors, apiFailures } = await openAppAs(page, TG);
  const planItems = (await api(page, "/api/v2/plan")).plan.plan_items as { program_inclusion_id: number | null }[];
  inclusionId = planItems.find((item) => item.program_inclusion_id !== null)?.program_inclusion_id ?? null;

  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
  await expect(page.getByText("Блок 1: 10×5")).toBeVisible();
  await expect(page.getByText("Блок 2: 5/5/5/5/5–8")).toBeVisible();
  await page.getByRole("button", { name: "Начать", exact: true }).click();

  const B = "Подтягивания — объём";
  const S = "Подтягивания — сила";
  const volume = Array.from({ length: 10 }, (_, i) => ({
    exercise: B, target: `Подход ${i + 1}/10 · Цель: 5 повт.`, value: "5", restAfter: i < 9 ? REST_30 : rest(15),
  }));
  await playSets(page, [
    ...volume,
    { exercise: S, target: "Подход 1/5 · Цель: 5 повт.", value: "5", restAfter: rest(3) },
    { exercise: S, target: "Подход 2/5 · Цель: 5 повт.", value: "5", restAfter: rest(3) },
    { exercise: S, target: "Подход 3/5 · Цель: 5 повт.", value: "5", restAfter: rest(3) },
    { exercise: S, target: "Подход 4/5 · Цель: 5 повт.", value: "5", restAfter: rest(3) },
    { exercise: S, target: "Подход 5/5 · Цель: 5–8 повт. (потолок 8)", value: "7", restAfter: null },
  ]);
  await expect(page.getByTestId("engine-confirm")).toContainText("Отдых не дольше 0:30");
  await answerChecksV2(page, "valid");
  await page.getByTestId("engine-confirm-submit").click();
  await expect(page.getByTestId("engine-complete")).toBeVisible();
  await page.getByTestId("engine-save").click();
  await expect(page.getByTestId("course-progression")).toContainText("Следующая тренировка A");
  await page.getByRole("button", { name: "Закрыть" }).click();

  // B закрыта полностью (10×5, техника и отдых 30 с подтверждены) → S < 20 → 11×5; A не тронута (8/7/7/7+).
  const course = await api(page, `/api/v2/program-inclusions/${inclusionId}/course`);
  expect(course.next_workout_role).toBe("A");
  expect([course.state.volume_b.sets, course.state.volume_b.reps]).toEqual([11, 5]);
  expect(course.state.volume_a.targets).toEqual([8, 7, 7, 7]);
  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByTestId("plan-week-progress").first()).toHaveText(/Текущая неделя · 2 из 2/);

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
