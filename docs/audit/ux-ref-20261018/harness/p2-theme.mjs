// Pass 2 · UX-18 recheck: in-app theme override «Тёмная» from Settings (Telegram scheme light) — readable?
import { Sess, OUT } from "./lib.mjs"; import { step, tab } from "./flows.mjs";
const s = await new Sess("p2-theme", 8800101).start(); const p = s.page;
await s.open("/"); await tab(s,"Профиль"); await s.tap(p.locator("button[aria-label='Настройки']"),"Настройки"); await step(s,"settings");
const sel = p.locator("select").filter({has: p.locator("option", {hasText:"Тёмная"})}).first(); const opts = await sel.evaluate(e=>[...e.options].map(o=>o.text)).catch(()=>null); s.ev(`THEME OPTIONS ${JSON.stringify(opts)}`);
if (opts) { await sel.selectOption({label:"Тёмная"}); } else { const r=p.getByRole("radio",{name:"Тёмная"}).or(p.getByRole("button",{name:"Тёмная"})).or(p.getByRole("tab",{name:"Тёмная"})).first(); await r.scrollIntoViewIfNeeded(); await r.click({force:true}); s.ev("CLICK Тёмная"); }
const save=p.getByRole("button",{name:/Сохранить/}).first(); if (await save.count()) await s.tap(save,"Сохранить");
await s.settle(); await s.shot("settings-dark");
for (const t of ["Главная","Планы"]) { await s.open("/"); if (t!=="Главная") await tab(s,t); await p.screenshot({ path: `${OUT}/p2-theme-dark-override-${t}.png` }); }
await s.end();
