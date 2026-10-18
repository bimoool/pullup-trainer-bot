// Pass 1 · aged/data-rich profiles on the SEEDED stand (8001): journal calendar + analytics + plans.
import { Sess, OUT } from "./lib.mjs"; import { step, tab } from "./flows.mjs";
for (const id of [970001, 900018, 990001]) {
  const s = await new Sess(`p1-aged-${id}`, id).start(); const p = s.page;
  await s.open("/"); await step(s,"home");
  for (const t of ["Планы","Журнал","Аналитика"]) { await tab(s,t); await s.dump(t); await p.screenshot({ path: `${OUT}/p1-aged-${id}-${t}.png`, fullPage: true }); }
  await s.end();
}
