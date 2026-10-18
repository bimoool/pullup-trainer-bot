// Pass 2 · E12: empty custom workout — editor offers «Добавить в план»? (fresh user 8800203, clean stand)
import { Sess } from "./lib.mjs"; import { step, tab, onboardFresh } from "./flows.mjs";
const s = await new Sess("p2-e12", 8800203).start(); const p = s.page;
await onboardFresh(s, "12");
await s.tap(p.getByRole("button",{name:"Создать тренировку"}),"Создать тренировку");
await p.locator("input").first().fill("AUDIT пустая"); await s.tap(p.getByRole("button",{name:"Создать и добавить упражнения"}),"Создать");
s.ev(`E12 editor buttons ${JSON.stringify(await p.getByRole("button").evaluateAll(b=>b.map(x=>[x.innerText.trim(),x.disabled])))}`);
await s.tap(p.getByRole("button",{name:"Добавить в план"}),"Добавить в план (empty)"); await step(s,"E12 after tap");
const d = p.getByRole("button",{name:"Пн"}); if (await d.count()) { await s.tap(d,"Пн"); await s.tap(p.getByRole("button",{name:"Добавить",exact:true}),"Добавить"); await step(s,"E12 after add"); }
await s.end();
