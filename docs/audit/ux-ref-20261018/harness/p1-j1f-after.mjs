// Pass 1 · J1 after completion (8800101): Journal card actions → Open → Analytics → Plans → Profile → reload.
import { Sess } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
const s = await new Sess("p1-j1f", 8800101).start(); const p = s.page;
await s.open("/"); await tab(s,"Журнал");
await s.tap(p.getByRole("button",{name:/По плану Подтягивания/}).first(),"journal card"); await s.shot("sheet");
await s.tap(p.getByRole("button",{name:"Открыть"}),"Открыть"); await step(s,"session-detail");
await p.screenshot({ path: `${(await import("./lib.mjs")).OUT}/p1-j1f-00-session-detail-full.png`, fullPage: true });
await back(s); await s.dump("after-back-from-detail");
await tab(s,"Аналитика"); await step(s,"analytics");
await p.screenshot({ path: `${(await import("./lib.mjs")).OUT}/p1-j1f-00-analytics-full.png`, fullPage: true });
const prog = p.getByRole("button",{name:"Программа"}).or(p.getByRole("tab",{name:"Программа"})).first(); if (await prog.count()) { await s.tap(prog,"Программа"); await step(s,"analytics-program"); }
await tab(s,"Планы"); await step(s,"plans-after");
await tab(s,"Профиль"); await step(s,"profile-after");
await s.reload(); await step(s,"profile-reload");
await s.end();
