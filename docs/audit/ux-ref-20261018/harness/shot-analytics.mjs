import { Sess, OUT } from "./lib.mjs"; import { tab } from "./flows.mjs";
const s = await new Sess("p1-an", 8800101).start(); const p = s.page;
await s.open("/"); await tab(s,"Аналитика"); await p.screenshot({ path: `${OUT}/p1-an-00-analytics-full.png`, fullPage: true }); await s.end();
