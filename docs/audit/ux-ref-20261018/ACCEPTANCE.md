# Acceptance on staging — candidate 0790221 (https://staging.app.bimoool.com)

Not production. Real Telegram client rendering was not verified (UX-34 still open, needs the owner's screenshot).

1. **Owner-shaped course (UX-32/01/08):** Планы → current week. Expect: card line «Расписание вашей версии курса: 3 занятия в неделю» (legacy connection) and, if rest rules block the rest of the week, «На этой неделе не все занятия уместятся…». Rows: «занятие N из 3»; blocked rows say «Доступно с <дата>» or «Не уместится на этой неделе» and have **no «Начать»**. No «switch to 2» action exists by design.
2. **A/Б (V5.6 connection):** rows named «Объём (А)» / «Сила (Б)» with «занятие N из M»; one spelling А/Б across Home, programme detail, plan, pre-start.
3. **Open my plan (UX-06):** programme detail → «Добавить в план» → «Открыть мой план».
4. **Electives (UX-33):** reachable from the course card («Факультативы: N из 2 на этой неделе»), from the rest-day banner «Сегодня отдых — можно факультатив», and Home «+» → «Факультатив»; submit → appears in Журнал; third attempt in 7 days → limit text; no subscription gate.
5. **Numbers (UX-03/04/14/17):** finish a workout (and finish early): Итог «Время», Журнал card, Журнал detail, Analytics minutes agree; 0 s shows «без длительности», never «0:00»; Analytics «Повторений в рабочих подходах» + combined total as in Журнал; Итог «Упражнений» counts exercises; Журнал detail shows the band/assistance per block.
6. **Expired subscription:** a row without access still shows «Начать» and opens the subscription sheet.
Evidence: `checkpoints/B-shots/`, gate summary in `checkpoints/COORDINATOR.md`.
