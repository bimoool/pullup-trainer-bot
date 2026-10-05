import { Sess } from "./lib.mjs";
const s = await new Sess("j2", 7200002).start(); const p = s.page;
const bodies=[]; p.on("response", async r=>{ if(r.url().includes("/api/v2/plan")||r.url().includes("/api/v2/me/plan")) bodies.push(r.request().method()+" "+r.url().replace("http://127.0.0.1:8092","")+" "+(await r.text().catch(()=>"")).slice(0,1500)); });
await s.open("/"); await s.tap(p.getByText("Планы",{exact:true}).last(),"tab Планы");
bodies.forEach(b=>s.ev("API "+b));
await s.end();
