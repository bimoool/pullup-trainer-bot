// Local pass (ours): row menu on week 2: actions, move Monday->Thursday (same day as another occurrence), remove with confirm.
import { Sess } from "./lib.mjs"; import { step, tab } from "./flows.mjs";
const s = await new Sess("l6", 8810002).start(); const p = s.page;
await s.open("/"); await tab(s,"Планы");
await s.tap(p.locator("button[aria-label='Следующая неделя']").first(),"next week");
await s.tap(p.getByRole("button",{name:"Действия: L Тяга, понедельник"}),"⋯ Monday row"); await step(s,"row-sheet");
await s.tap(p.getByRole("button",{name:"Перенести"}),"Перенести"); await step(s,"move-screen");
s.ev(`MOVE-BUTTONS ${JSON.stringify(await p.getByRole("button").allInnerTexts())}`);
await s.tap(p.getByRole("button",{name:"Чт",exact:true}),"Чт"); await step(s,"move-picked");
const ok = p.getByRole("button",{name:/Перенести|Сохранить|Готово/}).last(); await s.tap(ok, "confirm move"); await step(s,"after-move");
// remove
await s.tap(p.getByRole("button",{name:/Действия: L Тяга, четверг/}).first(),"⋯ Thursday row"); 
await s.tap(p.getByRole("button",{name:"Убрать из плана"}),"Убрать из плана"); await step(s,"remove-confirm");
await s.end();
