import { Sess } from "./lib.mjs";
const s = await new Sess("j3", 7200002).start(); const p = s.page;
await s.open("/"); await s.tap(p.getByText("Пустая").first(),"open Пустая");
await s.tap(p.getByRole("button",{name:"Добавить в план"}),"Добавить в план");
await s.tap(p.getByRole("button",{name:"Свободный пул"}),"Свободный пул");
await s.tap(p.getByRole("button",{name:"Добавить",exact:true}),"Добавить"); await s.dump("after add empty to plan"); await s.shot("empty-in-plan");
await s.end();
