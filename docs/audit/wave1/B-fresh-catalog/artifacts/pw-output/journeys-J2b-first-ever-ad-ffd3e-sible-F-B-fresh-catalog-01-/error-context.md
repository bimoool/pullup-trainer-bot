# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: journeys.spec.ts >> J2b first-ever add-to-plan with no plan (EXPECTED TO FAIL: item invisible, F-B-fresh-catalog-01)
- Location: audit/B-fresh-catalog/journeys.spec.ts:103:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByText('Текущая неделя · 0 из 1')
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByText('Текущая неделя · 0 из 1') with timeout 5000ms
  - waiting for getByText('Текущая неделя · 0 из 1')

```

```yaml
- paragraph: Привет, Audit!
- paragraph: Планы
- button "Мои тренировки":
  - heading "Мои тренировки" [level=6]
- tablist "Обзор плана":
  - tab "Сейчас" [selected]
  - tab "Завершённые"
- paragraph: Текущий план
- 'button "Действия: Текущий план"'
- paragraph: Курсов в плане нет. Добавьте курс на Главной.
- button "Выбрать курс на Главной":
  - heading "Выбрать курс на Главной" [level=6]
- button "Предыдущая неделя" [disabled]: ‹
- text: Неделя 1 · 5 окт – 11 окт База
- button "Следующая неделя": ›
- paragraph: Текущая неделя · 0 из 0
- progressbar "Прогресс недели"
- paragraph: На эту неделю пока ничего не запланировано.
- button "+ Добавить упражнение"
- navigation "Основная навигация":
  - button "Главная"
  - button "Планы"
  - button "Журнал"
  - button "Аналитика"
  - button "Профиль"
```

# Test source

```ts
  17  |   await page.locator("input").first().fill("8");
  18  |   await page.getByRole("button", { name: "Далее" }).click();
  19  |   await page.getByRole("button", { name: "Да", exact: true }).click();
  20  |   await page.getByRole("button", { name: "Продолжить" }).click();
  21  |   await page.getByLabel("Вес, кг").fill("78");
  22  |   await page.getByRole("button", { name: "Далее" }).click();
  23  |   await page.getByLabel("Рост, см").fill("180");
  24  |   await page.getByRole("button", { name: "Далее" }).click();
  25  |   await page.locator("select").selectOption("male");
  26  |   await page.getByRole("button", { name: "Далее" }).click();
  27  |   await page.getByLabel("Дата рождения").fill("1995-05-15");
  28  |   await page.getByRole("button", { name: "Далее" }).click();
  29  |   await page.locator("select").selectOption({ label: "Москва (UTC+3)" });
  30  |   await page.getByRole("button", { name: "Готово" }).click();
  31  |   await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();
  32  | }
  33  | 
  34  | async function runLive(page: Page, reps: string[]) {
  35  |   let i = 0;
  36  |   for (let guard = 0; guard < 40; guard++) {
  37  |     await page.waitForTimeout(300);
  38  |     const body = await page.locator("body").innerText();
  39  |     if (/Тренировка завершена/.test(body)) return;
  40  |     if (/ГОТОВЫ К СТАРТУ/.test(body)) { await page.getByRole("button", { name: "Начать" }).click(); continue; }
  41  |     if (/Как прошла тренировка/.test(body)) {
  42  |       await page.getByRole("button", { name: /Средне/ }).click();
  43  |       await page.getByRole("button", { name: "Сохранить и завершить" }).click(); continue;
  44  |     }
  45  |     if (await page.getByRole("button", { name: "Пропустить отдых" }).count()) { await page.getByRole("button", { name: "Пропустить отдых" }).click(); continue; }
  46  |     if (await page.getByLabel("Повторений").count()) {
  47  |       await page.getByLabel("Повторений").fill(reps[i++] ?? "5");
  48  |       await page.getByRole("button", { name: /^Готово$/ }).click(); continue;
  49  |     }
  50  |     if (await page.getByRole("button", { name: /^Готов$/ }).count()) { await page.getByRole("button", { name: /^Готов$/ }).click(); continue; }
  51  |     if (/Все подходы плана выполнены/.test(body)) { await page.getByRole("button", { name: "Завершить" }).first().click(); continue; }
  52  |   }
  53  |   throw new Error("live loop did not reach summary");
  54  | }
  55  | 
  56  | test("J1 zero-to-workout via catalogue program", async ({ page }) => {
  57  |   await openAs(page, ID + (11 - 11));
  58  |   await onboardViaUi(page);
  59  |   await page.getByText("Подтягивания", { exact: true }).first().click();
  60  |   await page.getByRole("button", { name: "Добавить в план" }).click();
  61  |   await expect(page.getByRole("button", { name: "В плане" })).toBeVisible();
  62  |   await page.reload(); await settle(page); // detail screen hides the tab bar; leave it like a user would (reload == reopen)
  63  |   await tab(page, "Планы").click();
  64  |   await expect(page.getByText("Текущая неделя · 0 из 3")).toBeVisible();      // >=1 actionable row
  65  |   await page.reload(); await settle(page);
  66  |   await tab(page, "Планы").click();
  67  |   await expect(page.getByRole("button", { name: "Начать" }).first()).toBeVisible();
  68  |   await page.getByRole("button", { name: "Начать" }).first().click();
  69  |   await runLive(page, ["8", "8", "7", "3"]);
  70  |   await page.getByRole("button", { name: "Закрыть" }).click();
  71  |   await tab(page, "Журнал").click();
  72  |   await expect(page.getByText("По плану")).toBeVisible();
  73  |   await tab(page, "Аналитика").click();
  74  |   await expect(page.getByText("Тренировок за 30 дней")).toBeVisible();
  75  |   await page.reload(); await settle(page);
  76  |   await tab(page, "Журнал").click();
  77  |   await expect(page.getByText("Подтягивания", { exact: true }).first()).toBeVisible();
  78  | });
  79  | 
  80  | test("J2 custom workout from nothing, library search + create-own, start, then plan, start from plan", async ({ page }) => {
  81  |   await openAs(page, ID + (12 - 11));
  82  |   await onboardViaUi(page);
  83  |   await page.getByRole("button", { name: "Создать тренировку" }).click();
  84  |   await page.getByPlaceholder("Например, 3 минуты подтягиваний").fill("Моя тренировка спины");
  85  |   await page.getByRole("button", { name: "Создать и добавить упражнения" }).click();
  86  |   await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  87  |   await page.getByLabel("Поиск упражнения").fill("Австралийские подтягивания");
  88  |   await expect(page.getByText("Ничего не найдено")).toBeVisible();
  89  |   await page.getByRole("button", { name: /Создать своё/ }).click();
  90  |   await page.getByRole("textbox", { name: "Повторения в подходе" }).fill("8");
  91  |   await page.getByRole("button", { name: "Добавить", exact: true }).click();
  92  |   await page.getByRole("button", { name: "Сохранить" }).click();
  93  |   await page.reload(); await settle(page);
  94  |   await expect(page.getByText("1 упражнение · 3 × 8")).toBeVisible();
  95  |   await page.getByText("Моя тренировка спины").first().click();
  96  |   await page.getByRole("button", { name: "Начать", exact: true }).click();
  97  |   await runLive(page, ["8", "7", "6"]);
  98  |   await page.getByRole("button", { name: "Закрыть" }).click();
  99  |   await tab(page, "Журнал").click();
  100 |   await expect(page.getByText("Свободная")).toBeVisible();
  101 | });
  102 | 
  103 | test("J2b first-ever add-to-plan with no plan (EXPECTED TO FAIL: item invisible, F-B-fresh-catalog-01)", async ({ page }) => {
  104 |   await openAs(page, ID + (13 - 11));
  105 |   await onboardViaUi(page);
  106 |   await page.getByRole("button", { name: "Создать тренировку" }).click();
  107 |   await page.getByPlaceholder("Например, 3 минуты подтягиваний").fill("W");
  108 |   await page.getByRole("button", { name: "Создать и добавить упражнения" }).click();
  109 |   await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  110 |   await page.getByText("Планка", { exact: true }).first().click();
  111 |   await page.getByRole("button", { name: "Добавить", exact: true }).click();
  112 |   await page.getByRole("button", { name: "Добавить в план" }).click();
  113 |   await page.getByRole("button", { name: "Ср", exact: true }).click();
  114 |   await page.getByRole("button", { name: "Добавить", exact: true }).click();
  115 |   await page.reload(); await settle(page);
  116 |   await tab(page, "Планы").click();
> 117 |   await expect(page.getByText("Текущая неделя · 0 из 1")).toBeVisible();
      |                                                           ^ Error: expect(locator).toBeVisible() failed
  118 | });
  119 | 
  120 | test("J3 empty workout cannot start and has an edit path", async ({ page }) => {
  121 |   await openAs(page, ID + (14 - 11));
  122 |   await onboardViaUi(page);
  123 |   await page.getByRole("button", { name: "Создать тренировку" }).click();
  124 |   await page.getByPlaceholder("Например, 3 минуты подтягиваний").fill("Пустая");
  125 |   await page.getByRole("button", { name: "Создать и добавить упражнения" }).click();
  126 |   await page.getByRole("button", { name: "Сохранить" }).click();
  127 |   await expect(page.getByTestId("workout-detail-start")).toBeDisabled();
  128 |   await expect(page.getByRole("button", { name: "Изменить" })).toBeVisible();
  129 | });
  130 | 
```