import { Sess } from "./lib.mjs";
const s = await new Sess("j1", 7200001).start();
await s.open("/"); const p = s.page;
await s.tap(p.getByText("Планы",{exact:true}).last(),"tab Планы");
await s.dump("Планы after add"); await s.shot("plans-after-add");
await s.reload(); await s.dump("Планы reload"); await s.shot("plans-after-reload");
s.ev("buttons "+JSON.stringify(await p.getByRole("button").allInnerTexts()));
await s.end();
