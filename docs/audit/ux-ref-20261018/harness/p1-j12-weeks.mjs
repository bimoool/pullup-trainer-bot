// Pass 1 · J12: week stepper → future weeks visible/startable? (8800101)
import { Sess } from "./lib.mjs"; import { step, tab } from "./flows.mjs";
const s = await new Sess("p1-j12", 8800101).start(); const p = s.page;
await s.open("/"); await tab(s,"Планы");
const labels = await p.locator("button").evaluateAll(b => b.map(x => [x.innerText.trim(), x.getAttribute("aria-label")]).filter(x=>x[0].length<3));
s.ev(`SMALL BUTTONS ${JSON.stringify(labels)}`);
const next = p.locator("button[aria-label*='лед' i], button[aria-label*='next' i]").first();
for (let w=2; w<=5; w++){ await s.tap(next,`next week`); await step(s,`week-${w}`); }
const st = p.getByRole("button",{name:"Начать"}).first(); if (await st.count()) { await s.tap(st,"Начать future"); await step(s,"future-start"); }
await s.end();
