// Local layout probe for «Подборки»: Chromium vs WebKit (iOS-like engine) at 320/360/390, light+dark with Telegram-like themeParams.
import { chromium, webkit } from "/private/tmp/claude-502/-Users-kirillv--Documents-Claude-Code-pullup-trainer-bot/7282ab1e-4824-4a8f-acc4-215feace71b3/scratchpad/pw/node_modules/@playwright/test/index.mjs";
import { initData, OUT } from "./lib.mjs"; import fs from "node:fs";
const BASE = "http://127.0.0.1:8012"; const log = [];
async function run(engine, name, width, scheme, id) {
  const browser = await engine.launch(); const ctx = await browser.newContext({ viewport:{width,height:800}, deviceScaleFactor:2, isMobile: name!=="webkit-desktop", hasTouch:true, colorScheme:scheme });
  await ctx.route("https://telegram.org/js/telegram-web-app.js", r => r.fulfill({ status:200, contentType:"application/javascript", body:"" }));
  const tp = scheme==="dark" ? {bg_color:"#17212b",text_color:"#f5f5f5",hint_color:"#708499",link_color:"#6ab3f3",button_color:"#5288c1",button_text_color:"#fff",secondary_bg_color:"#232e3c"} : {bg_color:"#ffffff",text_color:"#000000",hint_color:"#999999",link_color:"#2481cc",button_color:"#2481cc",button_text_color:"#fff",secondary_bg_color:"#efeff3"};
  await ctx.addInitScript(({raw,scheme,tp}) => { try{sessionStorage.setItem('tapps/launchParams', JSON.stringify(new URLSearchParams({tgWebAppPlatform:'ios',tgWebAppThemeParams:JSON.stringify(tp),tgWebAppVersion:'7.0'}).toString()));}catch(e){}
    window.TelegramWebviewProxy={postEvent(){}}; window.Telegram={WebApp:{initData:raw,initDataUnsafe:{},version:"7.0",platform:"ios",colorScheme:scheme,themeParams:tp,isVersionAtLeast:()=>true,ready(){},expand(){},close(){},setHeaderColor(){},setBackgroundColor(){},setBottomBarColor(){},disableVerticalSwipes(){},enableClosingConfirmation(){},disableClosingConfirmation(){},onEvent(){},offEvent(){},HapticFeedback:{impactOccurred(){},notificationOccurred(){},selectionChanged(){}}}}; }, {raw:initData(id), scheme, tp});
  const page = await ctx.newPage(); await page.goto(BASE+"/"); await page.waitForLoadState("networkidle").catch(()=>{}); await page.waitForTimeout(1500);
  
  await page.locator("input").first().fill("8"); await page.getByRole("button",{name:"Далее"}).click(); await page.waitForTimeout(600);
  await page.getByRole("button",{name:"Да",exact:true}).click(); await page.waitForTimeout(600);
  for (let i=0;i<10;i++){ const t = await page.evaluate(()=>document.body.innerText);
    if (/Твой вес/.test(t)) { await page.getByLabel("Твой вес в кг?").fill("78"); await page.getByRole("button",{name:"Далее"}).click(); }
    else if (/Рост в см/.test(t)) { await page.getByLabel("Рост в см?").fill("180"); await page.getByRole("button",{name:"Далее"}).click(); }
    else if (/Дата рождения/.test(t)) { await page.getByLabel("Дата рождения").fill("1995-05-15"); await page.getByRole("button",{name:"Далее"}).click(); }
    else if (await page.getByRole("button",{name:"Готово"}).count()) { await page.locator("select").selectOption({label:"Москва (UTC+3)"}); await page.getByRole("button",{name:"Готово"}).click(); break; }
    else if (await page.locator("select").count()) { await page.locator("select").selectOption("male"); await page.getByRole("button",{name:"Далее"}).click(); }
    else { const b = page.getByRole("button",{name:/^(Продолжить|Понятно|Далее)$/}).first(); if (await b.count()) await b.click(); }
    await page.waitForTimeout(700); }
  await page.waitForTimeout(2000);
  const row = page.locator("[data-testid=collections-row]"); const has = await row.count();
  const m = has ? await page.evaluate(() => { const r=document.querySelector("[data-testid=collections-row]"); const cards=[...r.querySelectorAll("[data-testid=collection-card]")]; const sc=r.querySelector("[class*=scroll],[class*=carousel],.home-programs-row")||r.children[1]; return { docScrollW: document.documentElement.scrollWidth, innerW: innerWidth, cards: cards.map(c=>{const b=c.getBoundingClientRect(); return {w:Math.round(b.width),h:Math.round(b.height),x:Math.round(b.x), clipped: c.scrollWidth>c.clientWidth}}), rowOverflowX: sc? getComputedStyle(sc).overflowX : null }; }) : null;
  if (has) await row.scrollIntoViewIfNeeded(); await page.screenshot({ path:`${OUT}/l8-${name}-${width}-${scheme}.png` });
  log.push(`${name} w=${width} ${scheme} row=${has} ${JSON.stringify(m)}`); console.log(log.at(-1)); await browser.close();
}
let id=8820000;
for (const [eng,name] of [[chromium,"chromium"],[webkit,"webkit"]]) for (const w of [320,360,390]) for (const s of ["light","dark"]) await run(eng,name,w,s,id++).catch(e=>console.log(name,w,s,"ERR",String(e).slice(0,200)));
fs.appendFileSync(`${OUT}/l8.log`, log.join("\n")+"\n");
