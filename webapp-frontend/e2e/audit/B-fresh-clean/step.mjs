// usage: node step.mjs <tgid> <script-file-of-actions>  : actions are JS lines evaluated with p in scope
import {launch,initData,newCtx,watch,dump,shot} from "./lib.mjs";
import fs from "node:fs";
const id = +process.argv[2]; const code = fs.readFileSync(process.argv[3],"utf8");
const b = await launch(); const ctx = await newCtx(b, initData(id)); const p = await ctx.newPage();
watch(p, m=>console.log(m)); 
const API=[]; p.on("request", r=>{ if(r.url().includes("/api/") && r.method()!=="GET") console.log("MUT", r.method(), r.url().replace("http://127.0.0.1:8091",""), (r.postData()||"").slice(0,200)); });
await p.goto("http://127.0.0.1:8091/"); await p.waitForTimeout(2500);
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
try { await new AsyncFunction("p","dump","shot","ctx", code)(p,dump,shot,ctx); } catch(e){ console.log("SCRIPT ERROR", e.message.slice(0,400)); await shot(p,"err-"+Date.now()); }
await b.close();
