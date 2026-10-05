// Exploratory helper (harness). Signs initData same way as fixtures/initData.ts.
import { createHmac } from "node:crypto";
import { chromium } from "/home/user/pullup-trainer-bot/webapp-frontend/e2e/node_modules/@playwright/test/index.mjs";
import fs from "node:fs";
export const BASE = "http://127.0.0.1:8091";
export const ART = "/home/user/pullup-trainer-bot/docs/audit/wave1/B-fresh-clean/artifacts";
export function initData(id, firstName="Audit") {
  const f = { user: JSON.stringify({ id, first_name: firstName }), auth_date: String(Math.floor(Date.now()/1000)), query_id: "AAEAAAAAAAAA" };
  const dcs = Object.keys(f).sort().map(k=>`${k}=${f[k]}`).join("\n").replace(/\//g,"\\/");
  const sk = createHmac("sha256","WebAppData").update("audit-token").digest();
  f.hash = createHmac("sha256", sk).update(dcs).digest("hex");
  return Object.keys(f).map(k=>`${k}=${encodeURIComponent(f[k])}`).join("&");
}
export async function newCtx(browser, raw, theme="light") {
  const ctx = await browser.newContext({ viewport:{width:390,height:844}, deviceScaleFactor:2, isMobile:true, hasTouch:true, colorScheme: theme });
  await ctx.tracing.start({screenshots:true, snapshots:true});
  await ctx.route("https://telegram.org/js/telegram-web-app.js", r=>r.fulfill({status:200,contentType:"application/javascript",body:""}));
  await ctx.addInitScript(({raw, theme})=>{
    window.Telegram = { WebApp: { initData: raw, initDataUnsafe:{}, version:"7.0", platform:"ios", colorScheme: theme, themeParams: theme==="dark"?{bg_color:"#17212b",text_color:"#f5f5f5",hint_color:"#708499",link_color:"#6ab3f3",button_color:"#5288c1",button_text_color:"#ffffff",secondary_bg_color:"#232e3c",section_bg_color:"#17212b",subtitle_text_color:"#708499",destructive_text_color:"#ec3942"}:{},
      isVersionAtLeast:()=>true, ready(){}, expand(){}, close(){}, setHeaderColor(){}, setBackgroundColor(){}, setBottomBarColor(){}, disableVerticalSwipes(){}, enableClosingConfirmation(){}, disableClosingConfirmation(){}, onEvent(){}, offEvent(){}, HapticFeedback:{impactOccurred(){},notificationOccurred(){},selectionChanged(){}} } };
  }, {raw, theme});
  return ctx;
}
export function watch(page, log) {
  page.on("console", m=>{ if(["error","warning"].includes(m.type())) log(`CONSOLE ${m.type()}: ${m.text().slice(0,300)}`); });
  page.on("pageerror", e=>log(`PAGEERROR: ${e.message.slice(0,300)}`));
  page.on("response", async r=>{ const u=r.url(); if(u.includes("/api/") && r.status()>=400){ let b=""; try{b=(await r.text()).slice(0,400)}catch{} log(`NETFAIL ${r.status()} ${r.request().method()} ${u.replace(BASE,"")} :: ${b}`);} });
}
export async function body(page){ return (await page.locator("body").innerText()).replace(/\n+/g," | ").slice(0,900); }
export async function shot(page,name){ await page.screenshot({path:`${ART}/${name}.png`}); }
export const EXE="/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
export const launch=()=>chromium.launch({executablePath:EXE});
export { chromium };
export async function dump(page, tag=""){
  const t = await body(page);
  const ctrls = await page.evaluate(()=>[...document.querySelectorAll("button,a,[role=button],[role=tab],input,textarea,select")].filter(e=>e.offsetParent!==null).map(e=>{const l=(e.getAttribute("aria-label")||e.innerText||e.placeholder||e.value||"").trim().replace(/\s+/g," ").slice(0,40);return `${e.tagName.toLowerCase()}${e.type?"["+e.type+"]":""}:${l}`}));
  console.log(`--- ${tag} url=${page.url().replace(BASE,"")}\nTEXT: ${t}\nCTRL: ${ctrls.join(" ; ")}`);
}
