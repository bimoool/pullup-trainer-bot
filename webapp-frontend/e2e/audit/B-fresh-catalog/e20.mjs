import { Sess } from "./lib.mjs";
const s = await new Sess("search", 7200003).start(); const p = s.page;
await s.open("/"); await s.tap(p.getByText("Что потренируем сегодня?").first(),"search");
await s.tap(p.getByText("Планка",{exact:true}).first(),"Планка"); await s.tap(p.getByRole("button",{name:"Пн",exact:true}),"Пн");
await s.tap(p.getByRole("button",{name:"Добавить",exact:true}),"Добавить"); await s.dump("after add"); await s.shot("after-add");
await s.reload(); await s.tap(p.getByText("Планы",{exact:true}).last(),"tab Планы"); await s.dump("Планы"); await s.shot("plans");
await s.end();
