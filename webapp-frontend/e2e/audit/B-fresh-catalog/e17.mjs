import { Sess } from "./lib.mjs";
const s = await new Sess("j4", 7200001).start(); const p = s.page; const tab=n=>p.getByText(n,{exact:true}).last();
await s.open("/"); await s.tap(tab("Планы"),"tab Планы"); await s.tap(p.getByText("Завершённые",{exact:true}),"Завершённые"); await s.dump("Завершённые"); await s.shot("completed-tab");
await s.tap(tab("Главная"),"Home"); await s.tap(p.getByText("Подтягивания",{exact:true}).first(),"card"); await s.dump("detail after removal"); 
await s.tap(p.getByRole("button",{name:/Добавить в план|В плане/}),"add again"); await s.dump("after re-add");
await s.reload(); await s.tap(tab("Планы"),"tab Планы"); await s.dump("Планы after re-add"); await s.shot("plans-readd");
await s.end();
