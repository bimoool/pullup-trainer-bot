// Pass 1 · J6 continued (8800102): picker row → configure → save → add to plan → start.
import { Sess } from "./lib.mjs"; import { step, tab, back } from "./flows.mjs";
const s = await new Sess("p1-j6c", 8800102).start(); const p = s.page;
const f = async (l) => s.ev(`FIELDS[${l}] ${JSON.stringify(await p.locator("input,select,textarea").evaluateAll(els=>els.map(e=>({t:e.tagName,type:e.type,v:e.value?.slice(0,20),l:(e.labels?.[0]?.innerText||e.getAttribute("aria-label")||e.placeholder||"").trim().slice(0,40),o:e.tagName==="SELECT"?[...e.options].map(o=>o.text).slice(0,12):undefined}))))}`);
await s.open("/"); await tab(s,"Планы"); await s.tap(p.getByRole("button",{name:"Мои тренировки"}),"Мои тренировки"); await step(s,"my-workouts");
await s.tap(p.getByText("AUDIT Моя тяга").first(),"open AUDIT"); await step(s,"edit");
s.ev(`DISABLED ${JSON.stringify(await p.getByRole("button").evaluateAll(b=>b.map(x=>[x.innerText.trim(),x.disabled])))}`); await s.tap(p.getByRole("button",{name:/Добавить упражнение/}).first(),"Добавить упражнение"); await step(s,"picker");
const row = p.getByText("Подтягивания", {exact:true}).first();
s.ev(`ROW role=${await row.evaluate(e=>{const c=e.closest("[role],a,button,li"); return c? (c.tagName+" role="+c.getAttribute("role")) : "none";})}`);
await s.tap(row,"row Подтягивания"); await step(s,"configure"); await f("configure");
await p.screenshot({ path: `${(await import("./lib.mjs")).OUT}/p1-j6c-00-configure-full.png`, fullPage: true });
await s.end();
