// Pass 1 · J10 (8800101): edit the free «Объём ×5» session: date → previous week, one set value → Journal + Analytics.
import { Sess } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
const s = await new Sess("p1-j10", 8800101).start(); const p = s.page;
const f = async (l) => s.ev(`FIELDS[${l}] ${JSON.stringify(await p.locator("input,select,textarea").evaluateAll(els=>els.map(e=>({t:e.tagName,type:e.type,v:e.value?.slice(0,20),l:(e.labels?.[0]?.innerText||e.getAttribute("aria-label")||e.placeholder||"").trim().slice(0,40)}))))}`);
await s.open("/"); await tab(s,"Журнал");
await s.tap(p.getByRole("button",{name:/Свободная Объём ×5/}).first(),"card Объём ×5"); await step(s,"sheet");
await s.tap(p.getByRole("button",{name:"Изменить"}).first(),"Изменить"); await step(s,"edit-form"); await f("edit-form");
await p.screenshot({ path: `${(await import("./lib.mjs")).OUT}/p1-j10-00-edit-full.png`, fullPage: true });
const date = p.locator("input[type=date], input[type=datetime-local]").first();
if (await date.count()) { const t = await date.getAttribute("type"); await date.fill(t==="date" ? "2026-10-14" : "2026-10-14T19:00"); }
const reps = p.locator("input[inputmode=numeric], input[type=number]").first(); if (await reps.count()) await reps.fill("10");
const save = p.getByRole("button",{name:/Сохранить/}).first(); await s.tap(save,"Сохранить"); await step(s,"after-save");
await tab(s,"Журнал").catch(()=>{}); await step(s,"journal");
await tab(s,"Аналитика"); await step(s,"analytics");
await s.end();
