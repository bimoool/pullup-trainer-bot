import { Sess } from "./lib.mjs";
const s = await new Sess("j2", 7200002).start(); const p = s.page;
await s.open("/"); await s.tap(p.getByText("Моя тренировка спины").first(),"open workout");
await s.tap(p.getByRole("button",{name:"Добавить в план"}),"Добавить в план");
await s.tap(p.getByRole("button",{name:"Ср",exact:true}),"Ср");
await s.tap(p.getByRole("button",{name:"Добавить",exact:true}),"Добавить (2nd, plan now exists)"); await s.dump("after add 2"); await s.shot("after-add2");
await s.reload();
await s.tap(p.getByText("Планы",{exact:true}).last(),"tab Планы"); await s.dump("Планы"); await s.shot("plans2");
await s.end();
