# Первый запуск на новом эмуляторе test_pixel6_play (2026-10-27)

| Шаг | Что сделано | Что видно |
|---|---|---|
| 1 | Создан AVD `test_pixel6_play` (Pixel 6, Android 15, Google Play image), вручную из config.ini эталона (без данных и без входа; avdmanager недоступен — нет Java). Порт 5556. | Загрузка успешна; Google-аккаунтов 0 |
| 2 | Установлены APK Crimpd 8.5.3 (8050300), скопированные с `ref_pixel6_play` (только пакеты base+4 split, данные приложения не копировались, вход не копировался) | Установка Success; `installerPackageName=null` |
| 3 | Запуск `com.crimpd.ui/.MainActivity` (3 раза, в т.ч. после force-stop Play) | Процесс Crimpd стартует и сразу уступает экран Google Play: «Sign in to find the latest Android apps…» (evidence/first_launch/01_play_store_signin_instead_of_crimpd.png). Экрана Crimpd не показано |
| 4 | Sideload-копия удалена | Эмулятор снова чистый |

Факты: установщик не Play; Crimpd не показывает свой первый экран. Гипотеза (не проверена): приложение требует установки из Google Play. Подмена установщика (`-i com.android.vending`) не выполнялась — это обход защиты приложения, нужно решение владельца.
Эталонный эмулятор: config.ini идентичен до/после (проверено diff).

## Диагностика «Google Play не открывается» (2026-10-28), только test_pixel6_play
| Проверка | Результат |
|---|---|
| Эмулятор, дата/время/часовой пояс | загружен; дата устройства = хосту (28 окт 10:16, Asia/Yekaterinburg), авто-время включено |
| Play Store 41.3.25-31, Play Services 24.23.35 | установлены, включены, не остановлены |
| Данные на эмуляторе | 0 сторонних пакетов, 0 аккаунтов — перезапуск безопасен |
| Экран | gms `AddAccount ErrorActivity` («Something went wrong»), Play — «Sign in» |
| logcat NetworkMonitor | `UnknownHostException`, `PROBE_DNS … Timeout` — DNS внутри эмулятора не работает; TCP наружу работал, ICMP на macOS не проходит (не показатель) |
| Хост | интернет есть; активен VPN (Happ, utun); публичные DNS по UDP с хоста не отвечают (8.8.8.8/1.1.1.1/9.9.9.9 таймаут), отвечает только DNS роутера 192.168.1.1 (0,02 с) |
| Попытка 1 | перезапуск с `-dns-server 8.8.8.8,1.1.1.1` — НЕ помогла (моя ошибка: эти DNS при VPN недоступны) |
| Попытка 2 | перезапуск с `-dns-server 192.168.1.1` — DNS отвечает, но у виртуального Wi-Fi первым стоит IPv6-DNS `fec0::3`: часть имён (accounts.google.com, android.clients.google.com) резолвилась 30 с и падала, HTTP-пробы ~48 с, вход давал «Something went wrong» |
| Исправление | отключён виртуальный Wi-Fi эмулятора (`svc wifi disable`, `svc data enable`): остаётся мобильная сеть с одним IPv4-DNS 10.0.2.3 — три имени Google резолвятся за ~1 с |
| Результат | Play открывается («Sign in»), окно входа Google загружается («Sign in with ease», NEXT/SKIP) — `evidence/first_launch/02_google_signin_window_ready.png`. Учётные данные не вводились, на экране ничего не нажато |

Запуск эмулятора: `emulator -avd test_pixel6_play -port 5556 -no-snapshot -no-boot-anim -no-audio -gpu auto -dns-server 192.168.1.1`, затем `adb -s emulator-5556 shell svc wifi disable; svc data enable`. Установщик не подменялся, проверки приложения не обходились, `ref_pixel6_play` не затрагивался.
Гипотеза (не доказана): медленный IPv6-DNS слежения `fec0::3` — причина задержек на Wi-Fi-сети; подтверждено только то, что при отключённом Wi-Fi имена резолвятся быстро.

## Веб-версия Crimpd вместо Google Play (2026-10-28, только чтение, без ввода данных)
| Что проверено | Результат |
|---|---|
| Официальная веб-версия | Есть: `https://my.crimpd.com` (ссылки «Use it on the Web» на crimpd.com); открывается без входа, показывает каталог (счётчики тренировок 0 без входа), боковое меню Home/Plans/History/Analytics/Profile/Help, плитки Create Custom Workouts (Upgrade), Log Cross-Training, Open Climbing Session, Assessment Tests |
| Вход | `/login`: вкладки Log In (Email или username + Password, «Forgot your password?») и Sign Up. Входа через Google/Apple на странице нет |
| Регистрация | Поля **Username, Email, Password**; под кнопкой «By clicking Sign up you agree to accept the terms and conditions and privacy policy» — нажатие кнопки = согласие с условиями. Телефон не запрашивается. Нужен реальный почтовый ящик (подтверждение почты на этом экране не показано) |
| Граница | Веб-аккаунт закрывает проверки, зависящие от аккаунта (онбординг, free-tier, Upgrade-баннеры, Time Zone, Grade System, Test→назначения, правила future-test-rules), но НЕ доказывает поведение Android-приложения (плеер, звук, жесты, offline, система Android). Для Android-сценариев нужен Google Play (Google-аккаунт, возможно с проверкой телефоном) |
| Что остановило меня | Создание аккаунта, ввод пароля и согласие с условиями — действия человека; почтовый ящик нужен отдельный, принадлежащий владельцу (временные и чужие не используются) |
