// Pass 1 · J6 (8800102): create custom plan W=2,2,0,2 with only AUDIT workout → weeks 1..4 → start.
import { Sess } from "./lib.mjs"; import { step, tab } from "./flows.mjs";
const s = await new Sess("p1-j6g", 8800102).start(); const p = s.page;
await s.open("/"); await tab(s,"Планы"); await s.tap(p.getByRole("button",{name:"Свой план по неделям"}),"Свой план по неделям");
const cbs = p.locator("input[type=checkbox]"); const n = await cbs.count();
for (let i=0;i<n;i++){ const l = await cbs.nth(i).evaluate(e=>e.labels?.[0]?.innerText.trim()); const want = l==="AUDIT Моя тяга" || l==="Повторять по кругу"; if ((await cbs.nth(i).isChecked()) !== want) { await cbs.nth(i).click(); } }
await p.getByLabel("Тренировок по неделям").fill("2 2 0 2");
await p.getByRole("button",{name:"Пн"}).click(); await p.getByRole("button",{name:"Чт"}).click();
await s.shot("custom-filled");
await s.tap(p.getByRole("button",{name:"Создать план"}),"Создать план"); await step(s,"after-create");
const next = p.locator("button[aria-label='Следующая неделя']").first();
for (let w=2; w<=4; w++){ if (!(await next.count())) break; await s.tap(next,"next week"); await step(s,`w${w}`); }
await s.end();
