import { Sess } from "./lib.mjs";
const s = await new Sess("j1", 7200001).start();
await s.open("/"); const p = s.page; const tab = n => p.locator("nav, [class*=tab], body").getByText(n,{exact:true}).last();
await s.tap(tab("Журнал"),"tab Журнал"); await s.dump("Журнал"); await s.shot("journal");
await s.tap(tab("Аналитика"),"tab Аналитика"); await s.dump("Аналитика"); await s.shot("analytics");
await s.tap(tab("Планы"),"tab Планы"); await s.dump("Планы"); await s.shot("plans-after-complete");
await s.end();
