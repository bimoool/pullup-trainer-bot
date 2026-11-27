# Блок 5: внутренние настройки (Crimpd 8.5.3, 2026-10-24; аккаунт владельца, обратимо)
Исходные значения (до): Length Unit Metric, Height 181 cm, Locale en-GB («Monday… start of the week»), Max Route Grade 6a, Time Zone Asia/Yekaterinburg.
| Настройка | Действие | Эффект | Восстановление и проверка |
|---|---|---|---|
| Length Unit | Metric→Imperial, Save | Profile: рост «6'0"»; в Settings текст «inches & feet»; при возврате в Metric рост стал **182 cm** (округление ft/in→cm: потеря 1 см) | выбран 181 cm колесом, Save, повторное открытие: «181 cm / centimeters» |
| Locale | English (UK)→English (US), Save | текст «Sunday will be used as the start of the week» (с «Monday»); код показывается как «en-us» | выбран English (UK), Save, повторное открытие: «en-gb» (**исходно «en-GB»** — регистр отображения изменился) |
| Max Route Grade | 6a→6b (колесо, Done, Save) | Profile: столбец Route Max стал 6b (rescan3_810) | колесом 6a, Save, повторное открытие: 6a |
| Time Zone | НЕ менялся | — | Причина: смена часового пояса пересчитает отображаемое время всех реальных логов владельца (Logbook/«Logged Workouts»), что затрагивает реальные записи; условие — одноразовый аккаунт |
| Grade System (French/Hueco) и остальные грейды | не менялись | — | Причина: смена системы грейдов может пересчитывать сохранённые значения с потерей точности (как рост ft/in→cm); условие — одноразовый аккаунт |
Инцидент: при проверке Locale неверифицированный тап открыл колесо Session Boulder Grade (показывало 9a+); отменено через Cancel без Done, Settings закрыт без сохранения; значения грейдов проверены повторным открытием.
