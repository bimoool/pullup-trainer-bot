import { expect, test } from "@playwright/test";

import { mockPlanContract } from "../fixtures/contractMock";
import { openAppAs } from "../fixtures/setup";

// Исполнитель B (ux-ref-20261018): путь «карточка курса → Открыть мой план → строки А/Б → старт» и
// факультативы (UX-33). Сиды — scripts/e2e_seed.py (ux_b_fresh / ux_b_legacy); до интеграции ветки A поля
// контракта достраивает fixtures/contractMock.ts поверх настоящего ответа стенда.
const FRESH_ID = 940_001;
const LEGACY_ID = 940_002;
const ELECTIVE_ID = 940_003;

test.describe("ux-b: план и факультативы", () => {
  test.fixme("(a) свежий профиль: курс → «Открыть мой план» → строки → старт", async ({ page }) => {
    await mockPlanContract(page);
    await openAppAs(page, FRESH_ID);
  });

  test.fixme("(b) устаревшее подключение: «1 из 3», пояснение, заблокированные строки говорят когда", async ({ page }) => {
    await mockPlanContract(page, {
      schedule: { sessions_per_week: 3, source: "catalogue", is_legacy: true, min_days_between_starts: 3, weekly_capacity: 2 },
    });
    await openAppAs(page, LEGACY_ID);
  });

  test.fixme("(c) факультатив: ≤ 2 касаний, отправка, Журнал, счётчик, лимит на третьем", async ({ page }) => {
    await mockPlanContract(page);
    await openAppAs(page, ELECTIVE_ID);
  });
});
