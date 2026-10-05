import {launch,initData,newCtx,watch,body,shot} from "./lib.mjs";
const b = await launch();
const ctx = await newCtx(b, initData(7100001));
const p = await ctx.newPage(); watch(p, console.log);
p.on("request", r=>{ if(r.url().includes("/api/")) console.log("REQ", r.method(), r.url().replace("http://127.0.0.1:8091","")); });
await p.goto("http://127.0.0.1:8091/"); await p.waitForTimeout(3000);
console.log("BODY", await body(p)); await shot(p,"s0-open");
console.log("URL", p.url());
await b.close();
