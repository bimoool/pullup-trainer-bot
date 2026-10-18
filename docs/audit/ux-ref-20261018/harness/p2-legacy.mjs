// Pass 2 · legacy course record in Journal (seeded 900018): «Удалить» — what happens? (disposable seeded stand 8001)
import { Sess, OUT } from "./lib.mjs"; import { step, tab } from "./flows.mjs";
const s = await new Sess("p2-legacy", 900018).start(); const p = s.page;
s.page.on("dialog", async d => { s.ev(`DIALOG ${d.type()} ${d.message().slice(0,200)}`); await d.dismiss(); });
await s.open("/"); await tab(s,"Журнал"); await p.screenshot({ path: `${OUT}/p2-legacy-00-journal-full.png`, fullPage: true });
await s.tap(p.getByRole("button",{name:"Удалить"}).first(),"Удалить (legacy)"); await step(s,"after-delete-tap");
await s.end();
