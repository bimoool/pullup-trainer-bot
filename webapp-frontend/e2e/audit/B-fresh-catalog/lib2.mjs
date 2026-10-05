export async function openEditor(s, name="Моя тренировка спины") {
  const p = s.page; await s.open("/");
  await s.tap(p.getByText(name).first(),"open workout");
  await s.tap(p.getByRole("button",{name:"Изменить"}),"Изменить");
}
export async function runLive(s, repsList = ["8","7","6","5","5","5"], { rpe = /Средне/, finish = true } = {}) {
  const p = s.page; let ri = 0;
  for (let i = 0; i < 40; i++) {
    await p.waitForTimeout(300);
    const t = await s.text();
    if (/ГОТОВЫ К СТАРТУ/.test(t)) { await s.tap(p.getByRole('button',{name:'Начать'}),'Начать (pre-session)'); continue; }
    if (/Тренировка завершена/.test(t)) { await s.dump("SUMMARY"); return "summary"; }
    if (/Как прошла тренировка/.test(t)) { await s.tap(p.getByRole("button",{name:rpe}),"RPE"); await s.tap(p.getByRole("button",{name:"Сохранить и завершить"}),"Сохранить и завершить"); continue; }
    const b = n => p.getByRole("button",{name:n});
    if (await b("Пропустить отдых").count()) { await s.tap(b("Пропустить отдых"),"Пропустить отдых"); continue; }
    if (await p.getByLabel("Повторений").count()) { const r = repsList[ri++] ?? "5"; await p.getByLabel("Повторений").fill(r); await s.tap(b(/^Готово$/),"Готово reps="+r); continue; }
    if (await b(/^Готов$/).count()) { await s.tap(b(/^Готов$/),"Готов"); continue; }
    if (/Все подходы плана выполнены/.test(t)) { if (!finish) return "ready-to-finish"; await s.tap(b("Завершить").first(),"Завершить"); continue; }
    await s.dump("UNRECOGNISED live state"); await s.shot("live-unrecognised"); return "stuck";
  }
  return "loop-end";
}
