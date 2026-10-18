// Pass 1 · J7 (direct ready workout, no plan credit) + J9 (external activity) + J8 (post-factum) — user 8800101.
import { Sess } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
const s = await new Sess("p1-j7", 8800101).start(); const p = s.page;
await s.open("/"); await s.tap(p.getByRole("button",{name:/^Объём ×5/}).first(),"Объём ×5"); await step(s,"workout-detail");
await p.screenshot({ path: `${(await import("./lib.mjs")).OUT}/p1-j7-00-workout-detail-full.png`, fullPage: true });
await back(s);
// J9/J8 via Journal «+ Записать»
await tab(s,"Журнал"); await s.tap(p.getByRole("button",{name:"+ Записать"}),"+ Записать"); await step(s,"record-menu");
const opts = await p.getByRole("button").allInnerTexts(); s.ev(`RECORD OPTS ${JSON.stringify(opts)}`);
const ext = p.getByRole("button",{name:/Другую активность|активност/i}).first();
if (await ext.count()) { await s.tap(ext,"Другую активность"); await step(s,"external-form");
  const f = await p.locator("input,select,textarea").evaluateAll(els=>els.map(e=>({t:e.tagName,type:e.type,l:(e.labels?.[0]?.innerText||e.getAttribute("aria-label")||e.placeholder||"").trim(),o:e.tagName==="SELECT"?[...e.options].map(o=>o.text).slice(0,15):undefined})));
  s.ev(`EXT FIELDS ${JSON.stringify(f)}`); }
await s.end();
