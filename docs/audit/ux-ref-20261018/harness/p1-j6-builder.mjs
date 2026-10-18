// Pass 1 · J6: custom workout builder (fresh user 8800102 on clean stand) — explore every step.
import { Sess } from "./lib.mjs"; import { step, tab, back, onboardFresh } from "./flows.mjs";
const s = await new Sess("p1-j6", 8800102).start(); const p = s.page;
await onboardFresh(s, "12");
await s.tap(p.getByRole("button",{name:"Создать тренировку"}),"Создать тренировку"); await step(s,"builder-1");
const f = async (l) => s.ev(`FIELDS[${l}] ${JSON.stringify(await p.locator("input,select,textarea").evaluateAll(els=>els.map(e=>({t:e.tagName,type:e.type,l:(e.labels?.[0]?.innerText||e.getAttribute("aria-label")||e.placeholder||"").trim().slice(0,40),o:e.tagName==="SELECT"?[...e.options].map(o=>o.text).slice(0,12):undefined}))))}`);
await f("builder-1");
await p.screenshot({ path: `${(await import("./lib.mjs")).OUT}/p1-j6-00-builder-full.png`, fullPage: true });
await s.end();
