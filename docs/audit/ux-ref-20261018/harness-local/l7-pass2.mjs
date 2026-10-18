// Local pass 2 (ours): back/cancel, reopen after reload, move to a PAST day / other week, stop plan.
import { Sess } from "./lib.mjs"; import { step, tab } from "./flows.mjs";
const s = await new Sess("l7", 8810002).start(); const p = s.page;
await s.open("/"); await tab(s,"Планы");
const next = () => p.locator("button[aria-label='Следующая неделя']").first();
await s.tap(next(),"next week");
// 1) open move screen then leave without saving (browser back + Отмена variants)
await s.tap(p.getByRole("button",{name:/Действия: L Тяга, четверг/}).first(),"⋯ Thu"); await s.tap(p.getByRole("button",{name:"Перенести"}),"Перенести");
s.ev(`MOVE-SCREEN-BUTTONS ${JSON.stringify(await p.getByRole("button").allInnerTexts())}`);
await p.keyboard.press("Escape"); await s.settle(); await step(s,"after-escape");
// 2) reload persistence
await s.reload(); await tab(s,"Планы"); await s.tap(next(),"next week"); await step(s,"after-reload-week2");
// 3) move into the current week's PAST day (Mon 12 Oct)
await s.tap(p.getByRole("button",{name:/Действия: L Тяга, четверг/}).first(),"⋯ Thu"); await s.tap(p.getByRole("button",{name:"Перенести"}),"Перенести");
await s.tap(p.getByRole("button",{name:/Неделя 1/}),"Неделя 1"); await s.tap(p.getByRole("button",{name:"Пн",exact:true}),"Пн");
await s.tap(p.getByRole("button",{name:"Сохранить"}),"Сохранить"); await step(s,"after-move-to-past");
// 4) week 1 now
await s.tap(p.locator("button[aria-label='Предыдущая неделя']").first(),"prev week"); await step(s,"week1-after");
await s.end();
