await p.getByRole("button",{name:"Планы",exact:true}).click(); await p.waitForTimeout(800);
await p.getByRole("button",{name:"Мои тренировки"}).click(); await p.waitForTimeout(1200);
await p.getByText("Мои подтягивания 2").first().click(); await p.waitForTimeout(1500);
await p.getByRole("button",{name:"Изменить"}).click(); await p.waitForTimeout(1000);
await p.getByRole("button",{name:"+ Добавить упражнение"}).click(); await p.waitForTimeout(1000);
await p.getByRole("searchbox").fill("Подтягивания"); await p.waitForTimeout(1000);
