# Проверка защиты драйвера (2026-10-25)
Действие: открыть боковое меню (тап по иконке меню), вызвать ct.tab('Home') при подсчёте отправленных тапов.
Результат: [('drawer open', True), ('refused', 'DRAWER OPEN: refusing bottom-tab tap (would hit drawer item)'), ('taps sent during tab()', 0), ('still logged in / drawer still open', True)]
После теста: меню закрыто выбором пункта Home (селектор, не Logout); обычный переход по вкладке Profile выполнен — ['menu', 'Kirill Vozzhaev']
