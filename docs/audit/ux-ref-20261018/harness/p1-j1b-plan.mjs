// Pass 1 · J1 continued (same user 8800101): add «Подтягивания» to plan → Plans → start.
import { Sess } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
const s = await new Sess("p1-j1b", 8800101).start(); const p = s.page;
await s.open("/"); await s.tap(p.getByRole("button",{name:/^Подтягивания/}).first(),"card Подтягивания");
const add = p.getByRole("button",{name:"Добавить в план"}); if (await add.count()) await s.tap(add,"Добавить в план"); await step(s,"after-add");
for (let i=0;i<4;i++){ const b = p.getByRole("button",{name:/^(Добавить|Подтвердить|Готово|Сохранить|Продолжить|Перейти к плану|Открыть план)/}).first(); if (!(await b.count())) break; const n=(await b.innerText()).trim(); await s.tap(b,n); await step(s,`add-${i}`); }
await back(s); await step(s,"after-back"); await tab(s,"Планы"); await step(s,"plans-with-course");
const start = p.getByRole("button",{name:/Начать/}).first();
if (await start.count()) { await s.tap(start,"Начать"); await step(s,"pre-start"); }
await s.end();
