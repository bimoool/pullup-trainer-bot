# Первый запуск на новом эмуляторе test_pixel6_play (2026-10-27)

| Шаг | Что сделано | Что видно |
|---|---|---|
| 1 | Создан AVD `test_pixel6_play` (Pixel 6, Android 15, Google Play image), вручную из config.ini эталона (без данных и без входа; avdmanager недоступен — нет Java). Порт 5556. | Загрузка успешна; Google-аккаунтов 0 |
| 2 | Установлены APK Crimpd 8.5.3 (8050300), скопированные с `ref_pixel6_play` (только пакеты base+4 split, данные приложения не копировались, вход не копировался) | Установка Success; `installerPackageName=null` |
| 3 | Запуск `com.crimpd.ui/.MainActivity` (3 раза, в т.ч. после force-stop Play) | Процесс Crimpd стартует и сразу уступает экран Google Play: «Sign in to find the latest Android apps…» (evidence/first_launch/01_play_store_signin_instead_of_crimpd.png). Экрана Crimpd не показано |
| 4 | Sideload-копия удалена | Эмулятор снова чистый |

Факты: установщик не Play; Crimpd не показывает свой первый экран. Гипотеза (не проверена): приложение требует установки из Google Play. Подмена установщика (`-i com.android.vending`) не выполнялась — это обход защиты приложения, нужно решение владельца.
Эталонный эмулятор: config.ini идентичен до/после (проверено diff).
