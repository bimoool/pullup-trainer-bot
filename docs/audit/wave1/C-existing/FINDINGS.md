# FINDINGS — C-existing (existing / realistic users)

Severity: suggested. Evidence paths are relative to `docs/audit/wave1/C-existing/`. DIAG = read after the failure was observed. Gaps in numbering (F-C-01, -04, -07, -10..13) are spec tags that turned out OK (no finding).
Not reproduced (owner symptoms): "cannot start any workout", "no plan", "plan with zero workouts" — for all 10 backfilled existing profiles Планы shows the current week with a startable row and Live starts and completes (J1, J6, J7, J8). Only domain rule `too_early` and the expired banner interfere (below).

## F-C-02 — Expired user can start and complete workouts; the paywall is only a text line  (P1, subscription/auth defect)
- Journey J6, profile audit_expired (7300006), step "Планы → Начать".
- Expected: clear paywall / no_access that blocks starting for a lapsed subscription.
- Actual: Планы shows the line "Нет активной подписки. Оформи её в боте, потом возвращайся сюда." but `Начать` stays enabled; pre-screen "ГОТОВЫ К СТАРТУ" -> Live -> 2 sets -> "Тренировка завершена" all succeed; session is saved (Журнал shows it after reload; Планы "1 из 3").
- Evidence: `artifacts/J6_audit_expired.trace.txt` (lines 06:39:45 "FAIL F-C-02 start not gated" ... 06:39:58), `J6_audit_expired__02_plans_expired.png`, `J6_audit_expired__03_after_expired_train.png`.
- Repro from S0: open as tg 7300006 → Планы → Начать → Начать → Готов → enter 10 → Готово (x2) → Завершить → 3 → Сохранить и завершить.
- DIAG: legacy `GET /api/workout/plan` returns `{"status":"no_access"}` for this user (curl), so the gate exists only on the legacy path (`app/web/routes.py:737`); the v2 live endpoints (`app/web/routes_v2.py:1584 POST /sessions/live` …) have no `SubscriptionService.has_access` check. The "owner's no_access" case = any user whose trial/subscription date has passed (cache stays `trial` until `refresh_status` is called, `app/services/subscription.py:89`): deterministic repro = profile audit_expired / audit_expired_b.
- Note the inverse risk: the banner is the ONLY signal, the CTA ("в боте") has no link/button.

## F-C-03 — Pre-start screen target differs from the Live target for returning (gap) users  (P2, plan-generation defect / legacy-v2 convergence)
- Journey J6 (also reproducible in J1-style start), profiles audit_expired (7300006) and audit_expired_b (7300008) — last workout 24 / 33 days ago (`readiness_status: gap_rollback`).
- Expected: the numbers shown before pressing Начать equal the Live plan.
- Actual: pre-screen "Цель 1: 9 повторений · 3 рабочих подхода"; Live "Подход 1/3 · Цель: 11 повт. 3×11"; summary "Новая цель 11 → 11". For non-gap users both are equal (7300001: 11/11, 7300005: 8/8).
- Evidence: `artifacts/J6_audit_expired.trace.txt` 06:39:49–06:39:53, `J6_audit_expired_b.trace.txt`, `…__01_plans_expired_b.png`.
- DIAG: pre-screen reads `GET /api/v2/dashboard/status` (applies gap rollback; `SessionPreScreen.tsx:114`), Live is built from the frozen `ProgramInclusion.progression_state` (backfill value 11).

## F-C-05 — Completed plan session in Журнал has no Изменить / Повторить / Удалить and no explanation  (P2, UX dead-end; valid domain rule behind it)
- Journey J5, profile audit_existing_active, session produced through the UI in J1 (2 of 4 sets, 10 reps instead of 11).
- Expected: open → edit values → save (the user logged a wrong rep count and cannot fix it).
- Actual: tap entry → sheet shows only "Открыть" / "Отмена"; detail page is read-only with no buttons. For comparison an activity entry offers Открыть / Изменить / Повторить / Удалить, and legacy cards have inline Изменить / Удалить.
- Evidence: `artifacts/J5a_audit_existing_active.trace.txt` 06:46:xx "FAIL F-C-05", `J5a_audit_existing_active__j5a_01_native_sheet.png`, `__j5a_02_native_detail.png`; API `GET /api/v2/sessions` -> `"can_edit": false, "can_delete": false`.
- DIAG: `app/services/session_deletion.py:_verdict` returns `REASON_PROGRAM` for sessions linked to a program inclusion (progression safety) — deliberate; the defect is that the UI neither explains it nor offers an alternative (e.g. correct the set).

## F-C-06 — Session detail titles both blocks "Упражнение"  (P3, frontend/API content gap)
- J5, same session. Expected "Подтягивания — объём/сила" or "Блок A/Б". Actual: two cards titled "Упражнение" with "План: 11 · 11 · 11 · 11 / Факт: 10 · 10" and "План: 3 / Факт: Не выполнено". Evidence `J5a_…__j5a_02_native_detail.png`. DIAG: `app/web/routes_v2.py:286 _catalog_exercise_names` deliberately drops names of role exercises (subcategory block_a/block_b).

## F-C-08 — Activity edit form cannot change duration/type  (P3, UX)
- J5, backdated activity «Плавание 0:40»: "Изменить" opens "Изменить тренировку | ДАТА | КАК ПРОШЛА ТРЕНИРОВКА? | КОММЕНТАРИЙ" only. Rating + comment edit persists after reload (PASS); duration/type are not editable (must delete and re-add). Evidence `J5a_…__j5a_03_edit_form.png`.

## F-C-09 — «Повторить» on an activity produces a different, mislabelled entry  (P2, API/backend or frontend state defect)
- J5, clone of «Плавание 12:00, 0:40, Усилие 2» (dialog text: "Будет создана новая завершённая запись с теми же упражнениями и результатами.").
- Expected: second «Плавание 0:40». Actual: new entry "Записана задним числом | Тренировка | 09:25 | Подходы — | Повторы — | Усилие 2" (type and duration lost, dated today by the dialog's default ДАТА); Аналитика lists it as "Без категории 1 · 11%" and "Тренировок за 30 дней" 8 → 9.
- Evidence: `artifacts/J5a_audit_existing_active.trace.txt` ("after Создать копию", "FAIL F-C-09" is the spec's count check), `J5a_…__j5a_04_clone.png`, `…__j5a_05_final.png`. DIAG: clone route `app/web/routes_v2.py:1367` → `SessionEditingService.clone` copies blocks/sets only; `activity_type`/`duration_seconds` columns (training_sessions) are not copied.

## F-C-14 — Deleting (or editing) a legacy workout does not change Аналитика  (P2, legacy/v2 convergence defect)
- J5b, profile audit_legacy_existing (3 legacy workouts + 1 elective + 1 native from J1). Edit of legacy workout 02.10 (block A set 1: 10 → 9) persists in Журнал after reload (PASS). Then "Удалить" (native confirm "Удалить эту тренировку? Это пересчитает цели всех следующих тренировок…"): entry disappears from Журнал after reload, but "Тренировок за 30 дней" stays 5 → 5.
- DIAG: `workouts` table has 2 rows for the user, `training_sessions` still has the backfilled copy id 15 (2026-10-02); Аналитика v2 reads training_sessions (copies are excluded only in Журнал/`/journal/days`, `routes_v2.py:1280`). So analytics diverge from journal for every legacy edit/delete.
- Evidence: `artifacts/J5b_audit_legacy_existing.trace.txt` (end), `…__j5b_03_final.png`.

## F-C-15 — After closing and reopening mid-rest, the logged-set chip and «Изменить» are gone  (P3, execution/live-session defect)
- J7: set 1 (10) logged; context closed; reopen → Live resumed in ОТДЫХ with the timer continuing (1:25), progress "1 / 3" but "Подход 1: 10 повт. · Изменить" is no longer shown. The set itself is preserved (summary "Подход 1: 10 повт. / Подход 2: 9 повт.", Журнал "Повторы 19"). Evidence `artifacts/J7_audit_persist.trace.txt` ("PARTIAL F-C-15").

## F-C-16 — Backfilled elective shows "Подходы 1" for a 4-set ladder  (P3, legacy/v2 convergence defect)
- J5b prev-month view: "Факультатив | Факультатив — подтягивания на максимум | 09:01 | Подходы 1 | Повторы 36 | Усилие —" for legacy elective 12/10/8/6 (36 reps = correct, sets wrong). Evidence `artifacts/J5b_audit_legacy_existing.trace.txt` ("prev week"), `…__j5b_02_prev_week.png`. Context: backfill packs the elective into one SetLog (docstring of `scripts/backfill_multi_program.py`).

## F-C-17 — `python scripts/seed_exercise_library.py` crashes as documented  (P3, tooling/seed illusion)
- Running the documented command: `sqlalchemy.exc.NoReferencedTableError: Foreign key associated with column 'exercises.owner_user_id' could not find table 'users'` (only models_program is imported). Works only if `app.db.models` is imported first. Evidence: PROFILES.md step 4; reproduce: `BOT_TOKEN=x DATABASE_URL=… .venv/bin/python scripts/seed_exercise_library.py`.

## F-C-18 — Профиль shows an expired trial as still running  (P2, subscription/auth defect)
- J6, audit_expired: Планы says "Нет активной подписки…", while Профиль → АККАУНТ says "Подписка : пробный период (осталось 0 дн., до 09.09.2026)" (date 26 days in the past; `users.subscription_status` is still `trial`). Two surfaces contradict each other; after the admin grant Профиль/Планы agree (banner gone). Evidence `J6_audit_expired.trace.txt` (STATE BEFORE GRANT Профиль), `J6_audit_expired__01_profile_expired.png`.

## F-C-19 — "Начать" on a too-early day leads to a text dead end  (P3, UX; domain rule is valid)
- J6, audit_trial (last workout 1 day ago, MIN_REST_DAYS=2): Планы row "0/3" with `Начать` and the line "Ещё рано для следующей тренировки — минимальный отдых между тренировками не прошёл."; tap → screen "ТРЕНИРОВКА · Ещё рано … · Перейти в обычную "Тренировку"". No date/time of the earliest start, the link label is unclear. The same user type 4 days after the last workout (audit_trial_rested) trains fine. Evidence `J6_audit_trial.trace.txt`, `J6_audit_trial__profile.png`.

## F-C-20 — Raw internal identifiers in the UI  (P3, content/UX)
- Главная category header "pull_ups"; Аналитика "По типам: pull_ups 7 · 100%" and "Сводка: pull_ups / block_a 3.5 / block_b 3.5 / Итого 7, Минуты 0" (fractional tallies, minutes 0). Evidence `J1_audit_existing_active__01_home.png`, `…__09_analytics.png`.

## Platform / reference-only observations (no finding)
- Console error "Telegram SDK init() failed … launch parameters" on every load = Playwright mock artefact (platform difference).
- Delete uses a native `window.confirm`; auto-accepted in specs, behaviour inside the real Telegram iOS WebView UNTESTED.
- Journal weeks are cut at the month boundary ("28 СЕН. – 4 ОКТ." in October view lists only 1–4 Oct; 29.09 appears in the Сентябрь view) — consistent, noted as UX.
- Week transition (J1 audit_returning_week_transition): app created the missing current week (Неделя 1 · 5 окт – 11 окт, 0/3, startable) — PASS; the stale PlanWeek has `week_number = -1` (visible only in DB).
