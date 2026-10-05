import { Sess } from "./lib.mjs";
const s = await new Sess("j8", 7200001).start(); const p = s.page;
await s.open("/"); await s.dump("resumed");
await s.tap(p.getByRole("button",{name:"Завершить"}).first(),"Завершить (partial 1/3)"); await s.dump("finish dialog"); await s.shot("finish-dialog");
await s.tap(p.getByRole("button",{name:/Средне/}),"RPE");
const btn = p.getByRole("button",{name:"Сохранить и завершить"}); s.ev("DOUBLE TAP Сохранить и завершить");
await Promise.allSettled([btn.dblclick({timeout:3000})]); await s.settle(1500); await s.dump("after double tap"); await s.shot("after-dbl");
await s.end();
