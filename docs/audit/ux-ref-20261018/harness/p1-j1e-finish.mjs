// Pass 1 · J1: confirm technique/rest → summary → Journal → card → Analytics → Profile → Plans counter → reload.
import { Sess } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
const s = await new Sess("p1-j1e", 8800101).start(); const p = s.page;
await s.open("/"); await s.shot("confirm-panel");
await p.screenshot({ path: `${(await import("./lib.mjs")).OUT}/p1-j1e-00-confirm-full.png`, fullPage: true });
const yes = p.getByRole("button",{name:"Да",exact:true}); const n = await yes.count();
for (let i=0;i<n;i++) { await yes.nth(i).click(); await p.waitForTimeout(150); }
s.ev(`CLICKED Да x${n}`);
await s.tap(p.getByRole("button",{name:"Подтвердить и завершить"}),"Подтвердить и завершить"); await step(s,"summary");
for (let i=0;i<3;i++){ const b=p.getByRole("button",{name:/^(Готово|Сохранить|Закрыть|На главную|В журнал|Продолжить)/}).first(); if(!(await b.count())) break; await s.tap(b,(await b.innerText()).trim()); await step(s,`post-summary-${i}`); }
await tab(s,"Журнал"); await step(s,"journal");
const card = p.getByRole("button",{name:/Подтягивания/}).first(); if (await card.count()) { await s.tap(card,"journal card"); await step(s,"journal-card"); await back(s); }
await tab(s,"Аналитика"); await step(s,"analytics");
await tab(s,"Планы"); await step(s,"plans-after");
await tab(s,"Профиль"); await step(s,"profile-after");
await tab(s,"Главная"); await step(s,"home-after");
await s.reload(); await step(s,"home-after-reload");
await s.end();
