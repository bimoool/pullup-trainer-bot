import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import type { APIRequestContext } from "@playwright/test";

import { buildInitData, getTestBotToken } from "./initData";

const COURSE_NAME = "Подтягивания";
const REPO_ROOT = fileURLToPath(new URL("../../../", import.meta.url));

/**
 * Journey-окружение: курс «Подтягивания» должен существовать БЕЗ пользовательских сидов.
 * Пока системный контент не доставляется миграциями (worker A, wave 1), хелпер заводит каталог через
 * scripts/backfill_multi_program.py::seed_catalog — только если курса нет. Когда курс едет миграцией,
 * хелпер — no-op (GET /programs уже его возвращает). Вызывать ПОСЛЕ онбординга (эндпоинт требует онбординга). Нужны DATABASE_URL и BOT_TOKEN сервера в env, python в PATH.
 */
export async function ensureCourseExists(request: APIRequestContext, baseURL: string, telegramId: number): Promise<void> {
  const initData = buildInitData({ id: telegramId, firstName: "E2E" }, getTestBotToken());
  const response = await request.get(`${baseURL}/api/v2/programs`, { headers: { "X-Telegram-Init-Data": initData } });
  const body = response.ok() ? ((await response.json()) as { programs: Array<{ name: string }> }) : { programs: [] };
  const programs = body.programs;
  if (programs.some((program) => program.name === COURSE_NAME)) {
    return;
  }
  execFileSync(
    process.env.E2E_PYTHON ?? "python",
    [
      "-c",
      "import asyncio, os\n"
      + "from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine\n"
      + "from scripts.backfill_multi_program import seed_catalog\n"
      + "async def main():\n"
      + "    engine = create_async_engine(os.environ['DATABASE_URL'])\n"
      + "    async with async_sessionmaker(engine, expire_on_commit=False)() as s:\n"
      + "        await seed_catalog(s)\n"
      + "        await s.commit()\n"
      + "    await engine.dispose()\n"
      + "asyncio.run(main())\n",
    ],
    { cwd: REPO_ROOT, env: { ...process.env, PYTHONPATH: REPO_ROOT }, stdio: "inherit" },
  );
}
