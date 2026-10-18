// Pass 1 · J6 (8800102): add exercise → save → «Добавить в план» sheet → «Свой план по неделям».
import { Sess } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
const s = await new Sess("p1-j6d", 8800102).start(); const p = s.page;
await s.open("/"); await tab(s,"Планы"); await s.tap(p.getByRole("button",{name:"Мои тренировки"}),"Мои тренировки");
await s.tap(p.getByText("AUDIT Моя тяга").first(),"open AUDIT");
await s.tap(p.getByRole("button",{name:/Добавить упражнение/}).first(),"Добавить упражнение");
await s.tap(p.getByText("Подтягивания",{exact:true}).first(),"row Подтягивания");
await s.tap(p.getByRole("button",{name:"Добавить",exact:true}),"Добавить"); await step(s,"after-add-ex");
const save = p.getByRole("button",{name:"Сохранить"}); if (await save.count()) { await s.tap(save,"Сохранить"); await step(s,"after-save"); }
const toPlan = p.getByRole("button",{name:"Добавить в план"}).first(); if (await toPlan.count()) { await s.tap(toPlan,"Добавить в план"); await step(s,"plan-sheet"); }
await s.end();
