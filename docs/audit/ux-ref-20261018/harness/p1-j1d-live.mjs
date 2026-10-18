// Pass 1 · J1: live session (resume for 8800101) → log all sets → summary → Journal → Analytics → reload.
import { Sess } from "./lib.mjs"; import { step, tab } from "./flows.mjs";
const s = await new Sess("p1-j1d", 8800101).start(); const p = s.page;
await s.open("/"); await step(s,"resume-open");
const go = p.getByRole("button",{name:/Продолжить|Вернуться к тренировке/}).first(); if (await go.count()) { await s.tap(go,"resume"); await step(s,"resumed"); }
for (let i=0;i<30;i++){
  const t = await s.text();
  if (/ИТОГ|Итоги|Тренировка завершена|Сохранить тренировку/i.test(t) && !/ЖИВАЯ ТРЕНИРОВКА/.test(t)) { await step(s,"summary"); break; }
  const inp = p.locator("input").first();
  const done = p.getByRole("button",{name:/^Готово$/});
  const now = p.getByRole("button",{name:/Начать сейчас|Пропустить|Дальше|Следующий подход|Продолжить/}).first();
  if (await done.count() && await inp.count()) { await inp.fill(i%3===2 ? "6" : "7"); if (i<3) await s.shot(`log-${i}`); await s.tap(done,"Готово"); await s.dump(`after-log-${i}`); if (i<2) await s.shot(`rest-${i}`); }
  else if (await now.count()) { await s.tap(now,(await now.innerText()).trim()); }
  else { const conf = p.getByRole("button").filter({hasNotText:/Завершить|Пауза/}).first(); await step(s,`unknown-${i}`); if (await conf.count()) await s.tap(conf,(await conf.innerText()).trim()); else break; }
}
await s.end();
