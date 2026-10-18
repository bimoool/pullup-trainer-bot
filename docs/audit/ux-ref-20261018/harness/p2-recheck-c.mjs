// Pass 2 · C: J10 set-value edit (8800101) and E12 empty workout from the editor (8800102), clean stand.
import { Sess, OUT } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
let s = await new Sess("p2-c-j10", 8800101).start(); let p = s.page;
await s.open("/"); await tab(s,"Журнал"); await s.tap(p.getByRole("button",{name:/Свободная Объём ×5/}).first(),"card"); await s.tap(p.getByRole("button",{name:"Изменить"}).first(),"Изменить");
await p.getByLabel("Подход 1: значение").fill("10"); await s.tap(p.getByRole("button",{name:"Сохранить"}),"Сохранить"); await step(s,"J10 journal after set edit");
await tab(s,"Аналитика"); await s.dump("J10 analytics after set edit"); await s.end();
s = await new Sess("p2-c-e12", 8800102).start(); p = s.page;
await s.open("/"); await s.tap(p.getByRole("button",{name:"Создать тренировку"}),"Создать тренировку");
await p.locator("input").first().fill("AUDIT пустая"); await s.tap(p.getByRole("button",{name:"Создать и добавить упражнения"}),"Создать");
s.ev(`E12 editor buttons ${JSON.stringify(await p.getByRole("button").evaluateAll(b=>b.map(x=>[x.innerText.trim(),x.disabled])))}`);
await s.tap(p.getByRole("button",{name:"Добавить в план"}),"Добавить в план (empty)"); await step(s,"E12 after tap");
const d = p.getByRole("button",{name:"Пн"}); if (await d.count()) { await s.tap(d,"Пн"); await s.tap(p.getByRole("button",{name:"Добавить",exact:true}),"Добавить"); await step(s,"E12 after add"); }
await s.end();
