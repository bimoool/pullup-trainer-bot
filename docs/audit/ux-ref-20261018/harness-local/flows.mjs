// Shared flows for the 2026-10-18 audit.
export const btns = async (s, l) => s.ev(`BUTTONS[${l}] ${JSON.stringify((await s.page.getByRole("button").allInnerTexts()).map(b=>b.trim().replace(/\s+/g," ")).filter(Boolean).slice(0,30))}`);
export const step = async (s, l) => { await s.dump(l); await btns(s, l); await s.shot(l); };
export async function onboardFresh(s, reps = "6") {
  const p = s.page; await s.open("/");
  await p.locator("input").first().fill(reps); await s.tap(p.getByRole("button",{name:"Далее"}),"Далее");
  await s.tap(p.getByRole("button",{name:"Да",exact:true}),"Да");
  for (let i=0;i<10;i++){
    const t = await s.text();
    if (/Твой вес/.test(t)) { await p.getByLabel("Твой вес в кг?").fill("78"); await s.tap(p.getByRole("button",{name:"Далее"}),"Далее"); }
    else if (/Рост в см/.test(t)) { await p.getByLabel("Рост в см?").fill("180"); await s.tap(p.getByRole("button",{name:"Далее"}),"Далее"); }
    else if (/Дата рождения/.test(t)) { await p.getByLabel("Дата рождения").fill("1995-05-15"); await s.tap(p.getByRole("button",{name:"Далее"}),"Далее"); }
    else if (await p.getByRole("button",{name:"Готово"}).count()) { await p.locator("select").selectOption({label:"Москва (UTC+3)"}); await s.tap(p.getByRole("button",{name:"Готово"}),"Готово"); return; }
    else if (await p.locator("select").count()) { await p.locator("select").selectOption("male"); await s.tap(p.getByRole("button",{name:"Далее"}),"Далее"); }
    else { const b = p.getByRole("button",{name:/^(Продолжить|Понятно|Далее)$/}).first(); if (await b.count()) await s.tap(b,"next"); else throw new Error("onboarding stuck: "+t.slice(0,200)); }
  }
}
export async function tab(s, name) { await s.tap(s.page.getByRole("link",{name}).or(s.page.getByRole("tab",{name})).or(s.page.getByRole("button",{name,exact:true})).last(), `TAB ${name}`); }
export async function back(s) { const b = s.page.getByRole("button",{name:/Назад|Back/}).first(); if (await b.count()) await s.tap(b,"Назад"); else { await s.page.goBack(); await s.settle(); s.ev("BROWSER BACK"); } }
