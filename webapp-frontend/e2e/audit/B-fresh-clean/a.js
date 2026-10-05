await p.getByLabel("Вес, кг").fill("78"); await p.getByRole("button",{name:"Далее"}).click(); await p.waitForTimeout(500);
await p.getByLabel("Рост, см").fill("180"); await p.getByRole("button",{name:"Далее"}).click(); await p.waitForTimeout(500);
await p.getByLabel("Пол").selectOption({label:"Мужской"}); await p.getByRole("button",{name:"Далее"}).click(); await p.waitForTimeout(500);
await p.getByLabel("Дата рождения").fill("1992-04-15"); await p.getByRole("button",{name:"Далее"}).click(); await p.waitForTimeout(500);
await p.getByLabel("Часовой пояс").selectOption({label:"Москва (UTC+3)"}); await p.getByRole("button",{name:"Готово"}).click(); await p.waitForTimeout(2500);
await dump(p,"after-onb"); await shot(p,"after-onb");
await p.reload(); await p.waitForTimeout(2500); await dump(p,"after-reload"); 
