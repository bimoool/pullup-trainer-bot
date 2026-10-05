import { Sess } from "./lib.mjs";
const s = await new Sess("j1", 7200001).start();
await s.open("/"); await s.newCtx(); const p = s.page; const tab = n => p.getByText(n,{exact:true}).last();
await s.tap(tab("Журнал"),"tab Журнал"); await s.dump("Журнал new ctx");
await s.tap(p.getByText("Подтягивания",{exact:true}).first(),"open journal entry"); await s.dump("entry"); await s.shot("journal-entry");
s.ev("buttons "+JSON.stringify(await p.getByRole("button").allInnerTexts()));
await s.end();
