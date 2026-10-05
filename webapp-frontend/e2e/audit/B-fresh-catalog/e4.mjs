import { Sess } from "./lib.mjs";
const s = await new Sess("j1", 7200001).start();
await s.open("/"); const p = s.page; const reps=["8","8","7","3","3","3","2"]; let ri=1;
for (let i=0;i<20;i++){
  const t = await s.dump("loop"+i);
  const has = n => p.getByRole("button",{name:n,exact:false}).count();
  if (await has("Пропустить отдых")) { await s.tap(p.getByRole("button",{name:"Пропустить отдых"}),"Пропустить отдых"); continue; }
  if (await has("Готов") && !(await p.getByLabel("Повторений").count())) { const g=p.getByRole("button",{name:/^Готов$/}); if(await g.count()){ await s.tap(g,"Готов"); continue; } }
  if (await p.getByLabel("Повторений").count()) { const r=reps[ri++]??"3"; await p.getByLabel("Повторений").fill(r); await s.tap(p.getByRole("button",{name:/^Готово$/}),"Готово reps="+r); continue; }
  await s.shot("stuck"+i); s.ev("buttons "+JSON.stringify(await p.getByRole("button").allInnerTexts())); break;
}
await s.end();
