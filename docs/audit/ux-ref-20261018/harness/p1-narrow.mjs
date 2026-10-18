// Pass 1 · narrow 320px light + dark on every tab (8800101 data-rich): horizontal overflow + touch targets < 44px.
import { Sess, OUT } from "./lib.mjs"; import { tab } from "./flows.mjs";
for (const scheme of ["light","dark"]) {
  const s = await new Sess(`p1-n320-${scheme}`, 8800101, { width: 320, height: 640, scheme }).start(); const p = s.page;
  await s.open("/");
  for (const t of ["Главная","Планы","Журнал","Аналитика","Профиль"]) {
    if (t!=="Главная") await tab(s,t);
    const m = await p.evaluate(() => { const over=[...document.querySelectorAll("body *")].filter(e=>{const r=e.getBoundingClientRect(); return r.width>0 && r.right>innerWidth+1;}).slice(0,5).map(e=>e.tagName+"."+(e.className||"").toString().slice(0,30)+":"+Math.round(e.getBoundingClientRect().right));
      const small=[...document.querySelectorAll("button,a[href],[role=button],input,select")].filter(e=>{const r=e.getBoundingClientRect(); return r.width>0&&r.height>0&&(r.width<43.5||r.height<43.5);}).map(e=>(e.getAttribute("aria-label")||e.innerText||e.tagName).trim().slice(0,18)+" "+Math.round(e.getBoundingClientRect().width)+"x"+Math.round(e.getBoundingClientRect().height));
      return { scrollW: document.documentElement.scrollWidth, over, small: small.slice(0,12), smallN: small.length }; });
    s.ev(`${t} ${JSON.stringify(m)}`);
    await p.screenshot({ path: `${OUT}/p1-n320-${scheme}-${t}.png`, fullPage: false });
  }
  await s.end();
}
