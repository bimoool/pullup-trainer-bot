// Local pass: OUR side of the plan journeys (isolated stand :8012, throwaway DB). Create custom workout -> add to plan -> volume/days.
import { Sess } from "./lib.mjs"; import { step, tab, onboardFresh } from "./flows.mjs";
const s = await new Sess("l1", 8810001).start(); const p = s.page;
await onboardFresh(s, "12"); await step(s, "home");
await tab(s, "Планы"); await step(s, "plans-empty");
await s.tap(p.getByRole("button",{name:"Создать тренировку"}),"Создать тренировку"); await step(s,"builder");
await s.end();
