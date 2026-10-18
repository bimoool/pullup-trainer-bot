// Pass 1 · J11: plan row shows «Не успеть на этой неделе» + «Ещё рано…» but offers «Начать» — what happens?
import { Sess } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
const s = await new Sess("p1-j11", 8800101).start(); const p = s.page;
await s.open("/"); await tab(s,"Планы"); await s.shot("plans");
await s.tap(p.getByRole("button",{name:"Начать"}).first(),"Начать (blocked row)"); await step(s,"after-start");
const b = p.getByRole("button",{name:/^Начать/}).first(); if (await b.count()) { await s.tap(b,"Начать again"); await step(s,"after-start-2"); }
await s.tap(p.getByRole("button",{name:"›"}).first(),"next week"); await step(s,"week-2");
await s.end();
