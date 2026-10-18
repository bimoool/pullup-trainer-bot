// Local pass (ours): what can be done with a planned occurrence (move / delete)? Tap the row, look for menus.
import { Sess } from "./lib.mjs"; import { step, tab } from "./flows.mjs";
const s = await new Sess("l4", 8810002).start(); const p = s.page;
await s.open("/"); await tab(s,"Планы"); await step(s,"week1");
s.ev(`ROWS ${JSON.stringify(await p.getByText("L Тяга").evaluateAll(els=>els.map(e=>({tag:e.tagName,parent:e.parentElement?.tagName,btns:[...e.closest("li,div[role],section,div")?.querySelectorAll("button,a")||[]].map(b=>(b.getAttribute("aria-label")||b.innerText).trim().slice(0,30))}))))}`);
await s.tap(p.getByText("L Тяга").first(),"tap row name"); await step(s,"after-row-tap");
await p.goBack().catch(()=>{}); await s.settle();
const row = p.getByText("L Тяга").first(); await row.click({button:"right"}).catch(()=>{}); await step(s,"after-contextmenu");
const box = await row.boundingBox(); if (box) { await p.mouse.move(box.x+5,box.y+5); await p.mouse.down(); await p.waitForTimeout(900); await p.mouse.up(); await s.settle(); await step(s,"after-longpress"); }
await s.end();
