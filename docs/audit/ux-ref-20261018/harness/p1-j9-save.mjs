// Pass 1 · J9 external activity save → Journal + Analytics; J7 direct start of a ready workout → plan unchanged.
import { Sess } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
const s = await new Sess("p1-j9", 8800101).start(); const p = s.page;
await s.open("/"); await tab(s,"Журнал"); await s.tap(p.getByRole("button",{name:"+ Записать"}),"+ Записать");
await s.tap(p.getByRole("button",{name:"Другую активность"}),"Другую активность");
await p.locator("select").selectOption({label:"Бег"}); await p.getByLabel("Длительность (ч:мм)").fill("0:45");
await s.tap(p.getByRole("button",{name:"Сохранить"}),"Сохранить"); await step(s,"after-save");
await tab(s,"Журнал").catch(()=>{}); await step(s,"journal");
await tab(s,"Аналитика"); await step(s,"analytics");
// J7
await tab(s,"Главная"); await s.tap(p.getByRole("button",{name:/^Объём ×5/}).first(),"Объём ×5");
await s.tap(p.getByRole("button",{name:"Начать"}),"Начать"); await step(s,"direct-start");
for (let i=0;i<20;i++){ const t=await s.text(); if (!/ЖИВАЯ ТРЕНИРОВКА/.test(t)) break;
  const inp=p.locator("input").first(), done=p.getByRole("button",{name:/^Готово$/}), now=p.getByRole("button",{name:/Начать сейчас/}).first(), fin=p.getByRole("button",{name:/Сохранить|Завершить тренировку|Подтвердить/}).first();
  if (await done.count() && await inp.count()) { await inp.fill("8"); await s.tap(done,"Готово"); }
  else if (await now.count()) await s.tap(now,"Начать сейчас");
  else if (await fin.count()) { await step(s,`fin-${i}`); await s.tap(fin,(await fin.innerText()).trim()); }
  else { await step(s,`unk-${i}`); break; } }
await step(s,"direct-summary");
const close=p.getByRole("button",{name:"Закрыть"}); if (await close.count()) await s.tap(close,"Закрыть");
await tab(s,"Планы"); await step(s,"plans-after-direct");
await tab(s,"Журнал"); await step(s,"journal-after-direct");
await s.end();
