# Crimpd Web (my.crimpd.com) — наблюдения без входа, 2026-10-28
**Это ВЕБ, не Android.** Выводы о приложении Android из них не делаются. Данные пользователя не вводились; встроенный браузер Claude, без аккаунта.

## Описание экрана регистрации (сохранено ДО отправки формы)
`/login` → вкладка Sign Up (форма пустая): поля **Username**, **Email**, **Password** (все пустые), синяя кнопка «Sign Up», под ней: «By clicking 'Sign up' you agree to accept the terms and conditions and privacy policy» (две ссылки). Вкладка Log In: «Email or username», «Password», «Forgot your password?». Входа через Google/Apple нет. Нажатие «Sign Up» = согласие с условиями. Форма оставлена открытой, пуста.

## Что видно без входа (чтение)
| Раздел (URL) | Что показано |
|---|---|
| `/workouts` (Home) | Поиск «Search Workouts», 11 карточек категорий в 4 группах (Endurance, Power Endurance, Strength & Power, Conditioning), плитки Create Custom Workouts (Upgrade), Log Cross-Training, Open Climbing Session, Assessment Tests. Сразу после загрузки счётчики «0 Workouts», через несколько секунд — реальные |
| Счётчики категорий | Aerobic Capacity 12, Regeneration 10, Aerobic Power 15, Anaerobic Capacity 23, Bouldering 12, Finger Strength 50, Power 6, Antagonist & Lower Body 7, Core 18, Flexibility 20, Upper Body 40 |
| Featured Playlists | 6 подборок (Paradigm Climbing 6, Emil Abrahamsson 15, Jonathan Sin 10, Stefano Ghisolfi 8, Josh Rundle 11, The Struggle 8 тренировок) |
| Assessment Tests | 11 тестов (Edge Lift, Finger Strength, One Arm, Front 3 Open Drag, Lactate Curve, Max Moves Foot on Campus, (Max Moves Test – Lattice Board на вебе в списке нет), Open Grip, Pinch Strength, Power Endurance 60%, Small Edges, Weighted Pull-up) с числом протоколов/минут |
| Plans (`/training-plan`) | «Training Plans», текст «Use Crimpd+ to build your own personalized training plans…», баннер CRIMPD+, «Start Your Training Plan», раздел Discover Skill Templates (4 первые карточки: Off-season Base Endurance, Build Power Endurance for Long Boulder Problems, Foundational Drills & Workouts for Boulderers, Apply Strength through Dynamic Movements) |
| History (`/calendar`), Analytics (`/analytics`), Profile (`/profile`) | **Без входа не показывают ни экран входа, ни свои данные — отрисовывается главная** (каталог). Отдельной страницы «войдите» нет |
| Неверный URL `/plans` | «Sorry, the page you are looking for does not exist» + кнопка Homepage |
Не сделано (требует входа или записи): всё, что создаёт данные; карточки тренировок/шаблонов не открывались в этом проходе.
Граница: счётчики и тексты веб-каталога не сверялись с Android-реестром (на Android категории считались по другой схеме: поиск 87/14/22/4/38/84/15).
