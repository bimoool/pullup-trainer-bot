// Pass 1 · J6 (8800102): add to plan on a day → Plans → «Свой план по неделям» editor.
import { Sess } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
const s = await new Sess("p1-j6e", 8800102).start(); const p = s.page;
const f = async (l) => s.ev(`FIELDS[${l}] ${JSON.stringify(await p.locator("input,select,textarea").evaluateAll(els=>els.map(e=>({t:e.tagName,type:e.type,v:e.value?.slice(0,20),l:(e.labels?.[0]?.innerText||e.getAttribute("aria-label")||e.placeholder||"").trim().slice(0,40),o:e.tagName==="SELECT"?[...e.options].map(o=>o.text).slice(0,12):undefined}))))}`);
await s.open("/"); await tab(s,"Планы"); await s.tap(p.getByRole("button",{name:"Мои тренировки"}),"Мои тренировки");
await s.tap(p.getByText("AUDIT Моя тяга").first(),"open AUDIT"); await s.tap(p.getByRole("button",{name:"Добавить в план"}).first(),"Добавить в план");
await s.tap(p.getByRole("button",{name:"Вс"}),"Вс"); await s.tap(p.getByRole("button",{name:"Добавить",exact:true}),"Добавить"); await step(s,"after-add-plan");
await back(s); await back(s); await tab(s,"Планы").catch(()=>{}); await step(s,"plans");
await s.tap(p.getByRole("button",{name:"Свой план по неделям"}),"Свой план по неделям"); await step(s,"custom-plan"); await f("custom-plan");
await p.screenshot({ path: `${(await import("./lib.mjs")).OUT}/p1-j6e-00-custom-plan-full.png`, fullPage: true });
await s.end();
