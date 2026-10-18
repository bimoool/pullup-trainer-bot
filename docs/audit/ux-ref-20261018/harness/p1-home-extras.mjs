// Pass 1 · Home search, «+», «Все ›», Tests; Profile achievements (8800101, clean stand).
import { Sess } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
const s = await new Sess("p1-home", 8800101).start(); const p = s.page;
await s.open("/");
await s.tap(p.getByRole("button",{name:"Что потренируем сегодня?"}),"search"); await step(s,"search");
const q = p.locator("input[type=search], input").first(); await q.fill("вис"); await s.settle(600); await step(s,"search-вис");
await q.fill("zzqq"); await s.settle(600); await step(s,"search-none");
await s.tap(p.getByRole("button",{name:"Закрыть"}),"Закрыть");
const plus = p.locator("button[aria-label]").filter({hasText:""}).first(); s.ev(`ARIA BUTTONS ${JSON.stringify(await p.locator("button[aria-label]").evaluateAll(b=>b.map(x=>x.getAttribute("aria-label")).slice(0,10)))}`);
const plusBtn = p.locator("header button, .home-search button").last(); if (await plusBtn.count()) { await s.tap(plusBtn,"+"); await step(s,"plus"); const c=p.getByRole("button",{name:"Отмена"}); if (await c.count()) await s.tap(c,"Отмена"); }
await s.tap(p.getByRole("button",{name:/^Тесты/}).first(),"Тесты"); await step(s,"tests"); await back(s);
await s.tap(p.getByRole("button",{name:"Все ›"}).first(),"Все ›"); await step(s,"all"); await back(s);
await tab(s,"Профиль"); await s.tap(p.getByRole("button",{name:/Ачивка/}).first(),"Ачивки"); await step(s,"achievements");
await s.end();
