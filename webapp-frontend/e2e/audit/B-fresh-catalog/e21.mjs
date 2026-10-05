import { Sess } from "./lib.mjs";
const s = await new Sess("dark", 7200004, {scheme:"dark"}).start(); const p = s.page; const tab=n=>p.getByText(n,{exact:true}).last();
const { onboard } = await import("./lib.mjs"); await onboard(s); await s.reload(); await s.shot("home");
await s.tap(tab("Планы"),"Планы"); await s.shot("plans-empty"); await s.tap(p.getByRole("button",{name:"Мои тренировки"}),"Мои тренировки"); await s.shot("myworkouts-empty");
await s.open("/"); await s.tap(tab("Журнал"),"Журнал"); await s.shot("journal-empty"); await s.tap(tab("Аналитика"),"Аналитика"); await s.shot("analytics-empty");
await s.end();
