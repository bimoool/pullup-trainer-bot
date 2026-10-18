// Pass 1 · J1: pre-start data form → live (same user 8800101).
import { Sess } from "./lib.mjs"; import { step, tab } from "./flows.mjs";
const s = await new Sess("p1-j1c", 8800101).start(); const p = s.page;
await s.open("/"); await tab(s,"Планы"); await s.tap(p.getByRole("button",{name:"Начать"}).first(),"Начать");
const t = p.locator("input[type=text]");
const vals = ["10","Audit band 25","красная","петля на перекладине","стопа","Audit band 35","зелёная","петля на перекладине","колено"];
for (let i=0;i<vals.length;i++) await t.nth(i).fill(vals[i]);
await s.tap(p.getByRole("button",{name:"Сохранить"}),"Сохранить"); await step(s,"after-save");
for (let i=0;i<3;i++){ const b=p.getByRole("button",{name:/^(Начать|Начать тренировку|Старт|Поехали)/}).first(); if(!(await b.count())) break; await s.tap(b,(await b.innerText()).trim()); await step(s,`start-${i}`); }
await s.end();
