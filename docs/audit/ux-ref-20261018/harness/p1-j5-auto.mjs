// Pass 1 · J5 (8800102): interval workout «3 минуты подтягиваний» with NO taps after start — does it advance by itself?
import { Sess } from "./lib.mjs"; import { step, tab } from "./flows.mjs";
const s = await new Sess("p1-j5", 8800102).start(); const p = s.page;
await s.open("/"); await s.tap(p.getByRole("button",{name:/^3 минуты подтягиваний/}).first(),"3 минуты");
await s.tap(p.getByRole("button",{name:"Начать"}),"Начать"); await s.tap(p.getByRole("button",{name:"Начать"}),"Начать (pre)");
for (let t=0; t<=48; t+=4) { const v = (await s.text()).replace(/\n/g," | ").slice(0,220); s.ev(`T+${t}s ${v}`); if (t===8||t===20) await s.shot(`t${t}`); await p.waitForTimeout(4000); }
await s.end();
