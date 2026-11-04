# Тренировки шаблонов навыков: точный список и механики (2026-10-26)

Список: **99 тренировок**, не открывавшихся раньше (из 119 уникальных названий в 31 уровне шаблонов минус 20, уже разобранных в `workout-protocols.csv`: Boulder Campus, Power Pulls A/B/C, Limit Power I/A/E, 7:3s, Max Hangs 85/90/95%, Weighted Pull Ups 85/90/95%, Deadlift A/B/C). Каждая открыта со страницы шаблона (Android AVD, Crimpd 8.5.3); полный разбор каждой — `template-workouts.csv` (99 строк: время, оборудование, упражнения с подходами/повторами/отдыхом, варианты A/B/C, строка нагрузки, грейд, зависимость от теста и грейда, где встречается). Тексты страниц — `evidence/template_workouts/*.json` (журнал владельца со страницы отрезан по заголовку «Logged Workouts», скриншоты не сохранялись). Упражнения не запускались (нажатие на упражнение открывает плеер — при проверке закрыт без записи).

Границы: описания (`Description`) у трёх семейств («Max Hangs – One Arm», «Small Edges 10mm», часть страниц) в дампе пусты — по ним есть только структура/нагрузка. Названия значков оборудования приложение текстом не отдаёт; расшифровка значков в CSV — по тому, какие упражнения их несут (вывод, не прочитанная подпись).

## Механики, общие для многих тренировок (описаны один раз)
1. **Схема страницы.** Заголовок + метка «Premium Workout» (36 из 99 помечены; открываются, но с подпиской) → «Start Workout / Log Workout / Favorite / Add to Plan» → краткое описание → значки оборудования и время (мин) → «Exercises»: на упражнение строка «N sets · M reps · время per rep» и отдельная строка «Rest …per rep & …per set» → при необходимости «Resistance» и «Target grade» → «Description». Нажатие на строку упражнения запускает плеер (не запись), крестик возвращает на страницу.
2. **Ступени A/B/C одной тренировки — отдельные тренировки с суффиксом, не вкладки.** Меняются только числа (подходы, повторы, время, отдых) и вес: см. таблицу различий ниже.
3. **«% of maximum» + вкладки A/B/C на странице** — только у «Max Hangs – One Arm 85/90/95%» (вкладки A 85% / B 90% / C 95%) и «Small Edges 10mm 70/80/90%» (A 70% / B 80% / C 90%): сама страница — одна тренировка, вкладки переключают процент от результата теста; строка Resistance вида «90% of max» без числа (One-arm: результат теста One Arm в этом наборе данных отсутствовал) либо «80% of maximum(−14 kg)» (Small Edges: число показывается — результат Small Edges Test есть).
4. **Замеры (тесты) — «Up to …».** Resistance = «Up to Max Load» (Finger Strength Test, 20 мм, 8×1×7 с, отдых 2:00; Small Edges Test, 10 мм, 8×1×7 с), «Up to 2RM» (Weighted Pull-up Test: 4–8 подходов по 2, отдых 3 мин), Finger Strength Test – One Arm (8×2×10 с, отдых 0:30/2:00), без Resistance — Hollow Body Hold Test (макс. время) и Hip Flexibility Test (одно значение).
5. **Нагрузка по RPE, не по тесту:** «Emil's Sub-max Daily Fingerboard Routine» (2/10 RPE), «Varied Grips B/C» (8/10 RPE).
6. **Грейд:** у 22 тренировок строка «Target grade» относительная («Flash Grade», «2 Grades Below Flash», «Limit», «Session Grade», «V0–V4», «Warm-up», «Various» …), в скобках — абсолютный грейд, вычисленный из настроек грейдов пользователя (поэтому он различается у пользователей). Грейд-зависимые: 1 On 1 Off, 1 On 2 Off, 50-50, 6 in 6, Aero 4's, Boulder Intervals, Boulder Triples, Broken Quarters, Capacity Power, Continuity 10×10, Continuity 5×3, Drop Intervals, Dynamic Climbing, Dyno Training, Efficiency Training, Hard Projecting, Linked Boulders, No Hands Slab, Strength Intervals, Style Triad, Varied ARC Session, Volume Bouldering.
7. **Без нагрузки в строке:** разминки, мобильность, кор, плечи/бицепс — нагрузка описана только числами повторов; вес свободный (гантели).
8. **Время на странице** — оценка приложения (мин), не сумма подходов: например «Route Pyramid» 100, «Capacity Power» 80.

## Различия внутри семейств (A/B/C и аналоги)
| Семейство | Что меняется между ступенями |
|---|---|
| Static Holds A/B/C | планка: 4×15 с → 4×30 с → 4×45 с; боковая планка 2×2 с тем же временем; отдых 0:45 → 0:30 → 0:15 |
| Floor Core A/B/C | A: скручивания и Dish Tuck 3×8, B: 3×15, C: Weighted Twist + V-Sit 4×15 (с гантелью) |
| Bar Core A/B/C | A: колени 3×10 + оконные дворники согнутые ноги, отдых 3:00; B: прямые ноги, отдых 2:00; C: 4×10, отдых 1:00 |
| Extended Core A/B/C | A: колени/«складной нож» 3×5, B: 3×10 с прямыми ногами, C: подъём к фронт-леверу 4×5; все с отдыхом 2:00; значок доп. снаряда |
| H-Core A/B/C | взвешенные скручивания и «прогиб»: 3×8/10 → 4×10/20 → 4×15/20, отдых 1:00 → 0:30 |
| Hip & Leg Flexibility A/B/C | шпагат в ящике и «бабочка»: 4×30 с → 4×60 с (бабочка 3×) → 3×90 с; время 30 → 35 → 40 мин |
| Upper Body Mobility A/B | A: 4 подхода по 30 с, B: 3 по 60 с, с добавлением Lat/QL; 25 → 35 мин |
| Active Hip Mobility A/B/C | выпады и Horse Squat 3×10/5 → 3×16/10 → C с утяжелением (гантели) 3×5; 15 → 25 → 25 мин |
| Active Posterior Chain A/B/C | RDL 3×5 + наклоны → RDL 3×10 + Pancake → утяжелённые 3×5, отдых 1:00 → 2:00 |
| Forearm Mobility / B | базовая растяжка сгибателей/разгибателей; B добавляет Wrist Rolls (значка оборудования нет) |
| Bicep Curls A/B | 6×10 (отдых 0:45) → 8×6 (отдых 1:00) |
| Press and Row A/B/C | 6×10 → 8×6 → 10×3; отдых 0:30 → 1:00 → 1:30; 15 → 25 → 35 мин |
| Bodyweight Repeaters A/B | 20 мм, 3×7 с: 4 подхода → 5; отдых 0:03 между повторами, 1:00 между подходами |
| Varied Grips B/C | 5 с → 7 с на хват, те же 4 хвата, 8/10 RPE |
| On the Minute A/B | подтягивания на каждой минуте: 5×3 → 5×5; B помечена «Body Weight» |
| One-arm Assisted Pull-ups A/B/C | 8 подходов по 1 → 2 → 3, отдых 1:30 (с помощью резины/блока) |
| One-arm Pull-ups A/B/C | A/B: 6×3 с помощью + lock-off / негативы; C: самостоятельные 6×2 + негативы |
| Max Hangs One Arm 85/90/95 | процент от результата теста (механика 3), структура одна: 6×2×10 с, отдых 0:30/1:30 |
| Small Edges 10 mm 70/80/90 | 5×1×7 с, отдых 2:00; процент от результата Small Edges Test |

## Остальное по отдельным тренировкам
См. `template-workouts.csv`: Finger Care, Hangboard Isometric Holds/Repeaters, Basic Grip Engagement, Emil's routine, Shoulder Shrugs (Bar/FB), One-arm Hang Prep, Scapular/Stabilizer Conditioning, Pull-up Negatives A, Campus Laddering/Latches, а также все трассовые (интервалы, пирамиды, ARC) и боулдеринговые (Triples, Linked Boulders, Style Triad, Strength/Drop Intervals и др.) форматы с грейдом.
