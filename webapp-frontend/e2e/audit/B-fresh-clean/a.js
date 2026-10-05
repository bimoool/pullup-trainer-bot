await p.getByRole("button",{name:/Пустая в плане/}).click(); await p.waitForTimeout(1200);
await p.getByRole("button",{name:"Записать"}).click(); await p.waitForTimeout(1200); await dump(p,"record-form");
