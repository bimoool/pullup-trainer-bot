# Реестр тестовых сущностей (Crimpd)
Правило: всё создаваемое в Crimpd называется `RESCAN TEST - ...`, записывается сюда сразу, удаляется в конце (если удаление возможно).
Прежний реестр REF-2: `~/android-ref-lab/TEST_DATA_LEDGER.md` (все объекты были удалены).
| ID | Дата | Что создано | Где | Статус |
|---|---|---|---|---|
| T-001 | 2026-10-21 | Custom workout «RESCAN TEST - Load» (Back Squat 2×1, Conditioning/Lower Body) | Crimpd Home → My Workouts | CREATED (delete at end) |
| T-002 | 2026-10-22 | Лог «Weighted Pull-up Test» 8×2, +10 кг (дата 22 Oct 2026) — ТЕСТОВЫЙ, влияет на результат в Profile и на «% of 2RM» | Crimpd Logbook / Profile / Analytics | DELETED 2026-10-22 (Delete Log + подтверждение); проверено: «90% of 2RM» снова +47 кг; Profile снова «Weighted Pull-up Test: Jul 20, +60 kg» |
| T-003 | 2026-10-22 | Cross-Training log «Running 15m», note «RESCAN TEST cross» | Logbook | DELETED 2026-10-22 (проверено: Analytics Cross-Training 0) |
| T-004a/b | 2026-10-22 | ДВА одинаковых лога «Running 15m», note «RESCAN offline» (дубликат после сбоя сети и повторного Save) | Logbook | DELETED ×2 2026-10-22 (каждый перед удалением проверен по заметке) |

Инцидент процесса 2026-10-22: при удалении дубликатов серия слепых тапов по координатам открыла карточку РЕАЛЬНОГО лога владельца («подтягивания на фб», 21 Oct 10:30 PM). Delete Log на этой карточке не нажимался (ниже экрана, поиск «Delete Log» не нашёл), запись и её данные на месте — проверено повторным просмотром Logbook. Дальше удаление только после проверки заметки «RESCAN».
Остаётся: T-001 (RESCAN TEST - Load + её лог). Системные настройки эмулятора (font_scale, night mode, сеть) возвращены к исходным.
| T-005 | 2026-10-22 | Training plan «RESCAN TEST - Plan» (blank, 6 weeks, start Nov 2) | Training Plans → Upcoming | DELETED 2026-10-22 (Delete Training Plan + подтверждение); Upcoming пуст, реальный план «In Progress» цел |
| T-006 | 2026-10-22 | Custom exercise «RESCAN Exercise» + workout «RESCAN TEST - CustomEx» | Home → My Workouts | (создаётся) |
| T-001b | 2026-10-22 | ДВА лога «RESCAN TEST - Load» (22 Oct 11:39) от double-tap Save | Logbook | DELETED ×2 2026-10-22; проверено: у тренировки остался только лог T-001 от 21 Oct |
