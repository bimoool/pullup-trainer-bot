await p.getByRole("button",{name:/Пустая в плане/}).click(); await p.waitForTimeout(1200);
await p.getByRole("button",{name:"Записать"}).click(); await p.waitForTimeout(1200);
await p.getByRole("button",{name:"Сохранить"}).click(); await p.waitForTimeout(1800); await dump(p,"after-save-record"); await shot(p,"E12-record-empty-saved");
await p.reload(); await p.waitForTimeout(2000); await p.getByRole("button",{name:"Журнал",exact:true}).click(); await p.waitForTimeout(1500); await dump(p,"journal");
