// Local pass (ours): add the SAME workout to Monday again (same day), then Wednesday; observe the week view.
import { Sess } from "./lib.mjs"; import { step, tab } from "./flows.mjs";
const s = await new Sess("l3", 8810002).start(); const p = s.page;
const openDetail = async () => { await s.open("/"); await tab(s,"Планы"); await s.tap(p.getByRole("button",{name:"Мои тренировки"}),"Мои тренировки"); await s.tap(p.getByText("L Тяга").first(),"open L Тяга"); };
for (const day of ["Пн","Ср"]) {
  await openDetail();
  await s.tap(p.getByRole("button",{name:"Добавить в план"}).first(),`Добавить в план (${day})`);
  await s.tap(p.getByRole("button",{name:day,exact:true}),day); await s.tap(p.getByRole("button",{name:"Добавить",exact:true}),"Добавить"); await step(s,`after-add-${day}`);
}
const next = p.locator("button[aria-label='Следующая неделя']").first(); s.ev(`next-week-btn count=${await next.count()}`);
await next.click().catch(()=>{}); await s.settle(); await step(s,"next-week");
await s.end();
