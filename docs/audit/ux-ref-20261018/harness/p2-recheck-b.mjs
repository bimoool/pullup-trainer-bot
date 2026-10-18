// Pass 2 · B (8800201): early finish → duration (UX-03), plan row after main (UX-01), J8 «Тренировку из моих», J10 set edit, E12 empty workout.
import { Sess, OUT } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
const s = await new Sess("p2-b", 8800201).start(); const p = s.page;
await s.open("/"); await p.waitForTimeout(20000); // let ~20 s of real time pass in the session
await s.tap(p.getByRole("button",{name:"Завершить"}),"Завершить");
for (const i of [0]) { const y=p.getByRole("button",{name:"Да",exact:true}); const n=await y.count(); for(let k=0;k<n;k++) await y.nth(k).click(); }
await s.tap(p.getByRole("button",{name:"Сохранить и завершить"}),"Сохранить и завершить"); await step(s,"UX-03 summary");
const c=p.getByRole("button",{name:"Закрыть"}); if (await c.count()) await s.tap(c,"Закрыть");
await tab(s,"Журнал"); await s.tap(p.getByRole("button",{name:/По плану Подтягивания/}).first(),"card"); await s.tap(p.getByRole("button",{name:"Открыть"}),"Открыть"); await step(s,"UX-03 detail"); await back(s);
await tab(s,"Планы"); await step(s,"UX-01 plan row");
// J8
await tab(s,"Журнал"); await s.tap(p.getByRole("button",{name:"+ Записать"}),"+ Записать"); await s.tap(p.getByRole("button",{name:"Тренировку из моих"}),"Тренировку из моих"); await step(s,"J8 picker");
const w = p.getByRole("button",{name:/W-лесенка/}).first(); if (await w.count()) { await s.tap(w,"W-лесенка"); await step(s,"J8 form"); const sv=p.getByRole("button",{name:/Сохранить/}).first(); if (await sv.count()) { await s.tap(sv,"Сохранить"); await step(s,"J8 after save"); } }
await s.end();
