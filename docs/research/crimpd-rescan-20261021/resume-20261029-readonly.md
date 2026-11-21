# Возобновление 2026-10-29: проверки чтением (без нового логина)

Правила: аккаунт владельца и `ref_pixel6_play` — только чтение; ничего не сохранялось, не включалось и не переключалось. Источники разделены: **[Android]** — эталонный эмулятор 5554 (Crimpd 8.5.3, `installerPackageName=com.android.vending`), **[Web-док]** — публичные страницы crimpd.com без входа. Веб-выводы на Android не переносятся.
Личные данные владельца в Settings (имя, e-mail, дата рождения) в запись не вносились.

## 1. Today, план, объяснения доступности — [Android]
- Дата устройства: Thu 29 Oct 2026 (+05). Training Plans → In Progress: один план, «Sep 21, 2026 through week of Oct 26, 2026», «Week 6 of 6», счётчик «0 / 4». Блок Today: **«No workouts scheduled for today»**.
- Причина видна только при открытии плана: Week 6 (PEAK, Oct 26 – Nov 1), 4 занятия в «THIS WEEK» с «0/1». Редактор «Week 6 Schedule» (открыт и закрыт **Cancel**, Save не нажимался): «Total sessions scheduled per day» = 0 на все 7 дней, у каждого из 4 занятий не выбран ни один день. То есть Today пуст не из-за блокировки, а потому что занятиям недели не назначены дни. На экране Today нет объяснения этого, нет подсказки «назначьте дни» и нет ссылки в редактор недели (только текст «No workouts scheduled for today»).
- Баннер на Training Plans: «Use Crimpd+ to build your own personalized training plans and access the full Crimpd workout library. Learn more».
- Статус-строка эмулятора показывает «3G» (прежняя форма сети эталона; в этом проходе сеть эталона не менялась).
- Ограничение: **Today с назначенным занятием не проверено** — создать назначение значит изменить план владельца (запрещено). Q09 остаётся требующим тестовой среды.

## 2. Настройки уведомлений — [Android]
- Внутри Settings **нет раздела уведомлений/дайджестов**. Разделы: профиль, Climber Profile (дата рождения, пол, единицы веса), начало недели, Time Zone, Route Settings (система грейдов + Max/Session/Flash), Bouldering Settings (Hueco/Font + три грейда), Appearance (Light/Dark/Auto), Timer Settings (Vibrations — выключено, Volume — слайдер), Download Logbook, Terms & Conditions, Privacy Policy, Delete Account (не открывался), версия 8.5.3.
- Разрешение системных уведомлений: `POST_NOTIFICATIONS granted=false` (USER_SET|USER_FIXED), appops `POST_NOTIFICATION: ignore`. Следствие: push и уведомление живого таймера на эталоне **не наблюдаемы**; менять разрешение запрещено.
- Отрицательное утверждение (ограничено): в экранах Settings 8.5.3 на Android нет переключателя push/дайджеста; настройки уведомлений — только системные.

## 3. Публичные условия и документация — [Web-док], не Android
- Pricing (crimpd.com/pricing): Free — «Over 75 workouts», logbook, analytics, ручной лог open climbing и cross training. Crimpd+ — «$4.99 per month, billed annually», 200+ workouts, custom plans, Skill Templates, Peer Insights, CSV export. **Внутренние противоречия страницы:** FAQ «Crimpd+ is billed monthly and can be cancelled at any time» vs «billed annually»; FAQ «full library of 75+ workouts» vs «200+» на карточке.
- Manage Subscription: при отмене доступ Crimpd+ сохраняется до конца оплаченного периода, затем аккаунт → Free. Созданные планы Crimpd+ **хранятся на серверах, но без активной подписки недоступны**; возврат — в течение 48 часов (iOS через Apple, Android через Google или support@crimpd.com). Для Q02 это публичное утверждение, не наблюдение.
- Redeem Code: на Android только для новых подписок, только через экран оплаты (Monthly → Focus your Training → способ оплаты → Redeem Code). Не проверялось (покупки запрещены).
- Build a Training Plan: активный план — один; длительность 1–24 недели (рекомендовано ≤12); фазы Base/Rest/Peak; цвета занятий недели (зелёный/жёлтый/красный = выполнено/частично/пропущено); начало недели настраивается; Skill Templates — 6 недель, цикл 2:1. Расхождения с наблюдениями — сверить отдельно (наблюдение: в плане владельца Week 6 = PEAK, 0 назначенных дней).
- Live Timer: на Android 13+ при первом запуске таймера запрашивается разрешение на уведомления; при отказе таймер и звуки работают, пропускается только уведомление. На iOS — Live Activities (16.2+). Это согласуется с `granted=false` на эталоне, но работа без разрешения на самом эмуляторе **не проверялась** (таймер не запускался).
- Data Export: ZIP из CSV (workouts, sets, observations), время в UTC, два места запуска (Analytics → Export Log Data; Settings → Download Logbook). Не запускалось.
- Информации о email/push-дайджестах в Docs/Pricing не найдено; блог содержит релизы (8.5 от 13 сентября 2026, live activities). Отрицательное утверждение ограничено просмотренными страницами.

## Что не сделано в этом блоке (с причиной)
Today с занятием, пересчёт Time Zone, смена грейдов — требуют изменения данных (запрещено на аккаунте владельца). Обрыв сети на эталоне — запрещено.
