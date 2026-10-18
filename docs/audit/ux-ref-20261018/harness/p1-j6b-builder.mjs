// Pass 1 · J6 continued (8800102): name → add exercise → configure → save → start/plan.
import { Sess } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
const s = await new Sess("p1-j6b", 8800102).start(); const p = s.page;
const f = async (l) => s.ev(`FIELDS[${l}] ${JSON.stringify(await p.locator("input,select,textarea").evaluateAll(els=>els.map(e=>({t:e.tagName,type:e.type,v:e.value?.slice(0,20),l:(e.labels?.[0]?.innerText||e.getAttribute("aria-label")||e.placeholder||"").trim().slice(0,40),o:e.tagName==="SELECT"?[...e.options].map(o=>o.text).slice(0,12):undefined}))))}`);
await s.open("/"); await s.tap(p.getByRole("button",{name:"Создать тренировку"}),"Создать тренировку");
await p.locator("input").first().fill("AUDIT Моя тяга"); await s.tap(p.getByRole("button",{name:"Создать и добавить упражнения"}),"Создать"); await step(s,"after-create"); await f("after-create");
const add = p.getByRole("button",{name:/Добавить упражнение|\+ Упражнение|Добавить/}).first(); if (await add.count()) { await s.tap(add,(await add.innerText()).trim()); await step(s,"picker"); await f("picker"); }
const ex = p.getByRole("button",{name:/Подтягивания/}).first(); if (await ex.count()) { await s.tap(ex,"pick Подтягивания"); await step(s,"after-pick"); await f("after-pick"); }
await p.screenshot({ path: `${(await import("./lib.mjs")).OUT}/p1-j6b-00-after-pick-full.png`, fullPage: true });
await s.end();
