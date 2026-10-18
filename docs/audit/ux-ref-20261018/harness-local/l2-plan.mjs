// Local pass (our side, :8012): custom workout -> custom plan with ONE day and volume 2 (same-day repeat?), then row affordances.
import { Sess } from "./lib.mjs"; import { step, tab, onboardFresh } from "./flows.mjs";
const s = await new Sess("l2", 8810002).start(); const p = s.page;
await onboardFresh(s, "12");
await s.tap(p.getByRole("button",{name:"Создать тренировку"}),"Создать тренировку");
await p.locator("input").first().fill("L Тяга"); await s.tap(p.getByRole("button",{name:"Создать и добавить упражнения"}),"Создать");
await s.tap(p.getByRole("button",{name:/Добавить упражнение/}).first(),"Добавить упражнение");
await s.tap(p.getByText("Подтягивания",{exact:true}).first(),"row Подтягивания");
await s.tap(p.getByRole("button",{name:"Добавить",exact:true}),"Добавить");
const save = p.getByRole("button",{name:"Сохранить"}); if (await save.count()) await s.tap(save,"Сохранить"); await step(s,"workout-saved");
const toPlan = p.getByRole("button",{name:"Добавить в план"}).first(); if (await toPlan.count()) { await s.tap(toPlan,"Добавить в план"); await step(s,"plan-sheet"); }
await s.end();
