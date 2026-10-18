// Pass 1 · J1 on a CLEAN install (port 8002): onboarding → Home → «Подтягивания» → plan → start.
import { Sess } from "./lib.mjs"; import { step, onboardFresh, tab } from "./flows.mjs";
const s = await new Sess("p1-j1", 8800101).start(); const p = s.page;
await s.open("/"); await step(s,"onb-zamer");
await onboardFresh(s); await step(s,"home");
const nav = await p.locator("nav a, nav button, [role=tablist] *").allInnerTexts(); s.ev(`NAV ${JSON.stringify(nav)}`);
for (const t of ["Планы","Журнал","Аналитика","Профиль"]) { try { await tab(s,t); await step(s,`empty-${t}`); } catch(e) { s.ev(`NO TAB ${t}: ${e.message.slice(0,120)}`); } }
await tab(s,"Главная"); await s.tap(p.getByRole("button",{name:/^Подтягивания/}).first(),"card Подтягивания"); await step(s,"program-detail");
await s.end();
