import { Sess } from "./lib.mjs"; import { runLive } from "./lib2.mjs";
const s = await new Sess("j2", 7200002).start(); const p = s.page;
await s.open("/"); await s.tap(p.getByText("Планы",{exact:true}).last(),"tab Планы");
await s.tap(p.getByRole("button",{name:"Начать"}),"Начать (plan row)");
const r = await runLive(s,["9","8","7"]); s.ev("RESULT "+r); await s.shot("summary");
await s.tap(p.getByRole("button",{name:"Закрыть"}),"Закрыть");
await s.tap(p.getByText("Планы",{exact:true}).last(),"tab Планы"); await s.dump("Планы after plan-run"); await s.shot("plans-after");
await s.tap(p.getByText("Журнал",{exact:true}).last(),"tab Журнал"); await s.dump("Журнал");
await s.end();
