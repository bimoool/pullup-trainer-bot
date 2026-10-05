import { Sess } from "./lib.mjs";
const s = await new Sess("j4", 7200001).start(); const p = s.page;
await s.open("/"); await s.dump("resumed");
await s.tap(p.getByRole("button",{name:/^Готов$/}),"Готов"); await s.dump("go"); await s.shot("plank-go");
s.ev("buttons "+JSON.stringify(await p.getByRole("button").allInnerTexts()));
s.ev("inputs "+JSON.stringify(await p.locator("input").evaluateAll(els=>els.map(e=>e.getAttribute("aria-label")+"|"+e.type+"|"+e.value))));
await p.waitForTimeout(3000); await s.dump("after 3s");
await s.end();
