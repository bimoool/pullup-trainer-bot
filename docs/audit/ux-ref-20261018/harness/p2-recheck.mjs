// Pass 2 · independent recheck on a NEW user 8800201 (clean stand): UX-01/02/03/04/05/06 + reload & early-finish states.
import { Sess, OUT } from "./lib.mjs"; import { step, tab, back, onboardFresh } from "./flows.mjs";
const s = await new Sess("p2-recheck", 8800201).start(); const p = s.page;
await onboardFresh(s, "6");
await tab(s,"Профиль"); await s.dump("UX-05 profile before workout");
await tab(s,"Главная"); await s.tap(p.getByRole("button",{name:/^Подтягивания/}).first(),"Подтягивания"); await s.tap(p.getByRole("button",{name:"Добавить в план"}),"Добавить в план"); await step(s,"UX-06 after add");
await back(s); await tab(s,"Планы"); await s.tap(p.getByRole("button",{name:"Начать"}).first(),"Начать");
const t = p.locator("input[type=text]"); const vals=["10","B25","красная","петля","стопа","B35","зелёная","петля","колено"]; for (let i=0;i<vals.length;i++) await t.nth(i).fill(vals[i]);
await s.tap(p.getByRole("button",{name:"Сохранить"}),"Сохранить"); await s.tap(p.getByRole("button",{name:"Начать"}),"Начать");
await s.tap(p.getByRole("button",{name:"Начать сейчас"}),"Начать сейчас");
await p.locator("input").first().fill("7"); await s.tap(p.getByRole("button",{name:/^Готово$/}),"Готово (set 1)");
await s.reload(); await step(s,"STATE reload mid-live");
const resume = p.getByRole("button",{name:/Продолжить|Вернуться/}).first(); if (await resume.count()) await s.tap(resume,"resume");
await s.tap(p.getByRole("button",{name:"Завершить"}),"Завершить (early)"); await step(s,"STATE early finish dialog");
await p.screenshot({ path: `${OUT}/p2-recheck-early-finish-full.png`, fullPage: true });
await s.end();
