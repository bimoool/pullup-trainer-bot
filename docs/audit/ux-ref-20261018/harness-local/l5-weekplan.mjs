// Local pass (ours): weekly custom plan "2 2 0 2" on Mon+Thu, then week 2 row menu (move/remove), same-day move.
import { Sess } from "./lib.mjs"; import { step, tab } from "./flows.mjs";
const s = await new Sess("l5", 8810002).start(); const p = s.page;
await s.open("/"); await tab(s,"Планы"); await s.tap(p.getByRole("button",{name:"Свой план по неделям"}),"Свой план по неделям"); await step(s,"form");
const cbs = p.locator("input[type=checkbox]"); const n = await cbs.count();
for (let i=0;i<n;i++){ const l = await cbs.nth(i).evaluate(e=>e.labels?.[0]?.innerText.trim()); const want = l==="L Тяга"; if ((await cbs.nth(i).isChecked()) !== want) await cbs.nth(i).click(); }
await p.getByLabel("Тренировок по неделям").fill("2 2 0 2");
await p.getByRole("button",{name:"Пн"}).click(); await p.getByRole("button",{name:"Чт"}).click();
await s.tap(p.getByRole("button",{name:"Создать план"}),"Создать план"); await step(s,"after-create");
const next = p.locator("button[aria-label='Следующая неделя']").first(); await s.tap(next,"next week"); await step(s,"week2");
s.ev(`ALL-BUTTONS ${JSON.stringify(await p.locator("button").evaluateAll(b=>b.map(x=>(x.getAttribute("aria-label")||x.innerText).trim()).filter(Boolean)))}`);
const dots = p.locator("button[aria-label*='Действия'], button[aria-label*='Ещё'], button:has-text('⋯')"); s.ev(`menu-buttons=${await dots.count()}`);
if (await dots.count()) { await s.tap(dots.first(),"⋯"); await step(s,"row-sheet"); }
await s.end();
