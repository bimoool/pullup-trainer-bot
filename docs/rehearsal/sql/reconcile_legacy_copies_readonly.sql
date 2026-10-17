-- Только чтение (BEGIN READ ONLY ... ROLLBACK). Разбор фазы 8 выката c03deff: «TrainingSession обычные всего: 74 (ожидается 73)».
-- Выводит только id, статусы и даты — без персональных данных. PR #339, docs/incidents.md.
BEGIN TRANSACTION READ ONLY;
-- 1) Числа ровно так, как их считал backfill до исправления, и так, как после.
SELECT
  (SELECT count(*) FROM workouts w JOIN users u ON u.id = w.user_id
     WHERE w.status = 'completed' AND u.onboarding_completed_at IS NOT NULL)            AS expected_onboarded_completed_workouts,
  (SELECT count(*) FROM training_sessions WHERE source <> 'elective')                   AS old_actual_all_non_elective,
  (SELECT count(*) FROM training_sessions ts WHERE ts.origin = 'legacy_backfill'
     AND ts.legacy_id IN (SELECT w.id FROM workouts w JOIN users u ON u.id = w.user_id
                          WHERE w.status = 'completed' AND u.onboarding_completed_at IS NOT NULL)) AS new_actual_matched_copies;
-- 2) Разбивка всех не-elective сессий по происхождению и статусу.
SELECT coalesce(origin, '(null)') AS origin, source, status, count(*)
FROM training_sessions WHERE source <> 'elective'
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
-- 3) Каждая не-elective сессия, которая НЕ является копией завершённой тренировки онбордившегося пользователя,
--    с причиной. Только идентификаторы и даты, без персональных данных.
SELECT ts.id, ts.user_id, coalesce(ts.origin, '(null)') AS origin, ts.source, ts.status, ts.legacy_id,
       ts.engine_version, ts.performed_at, ts.created_at,
       CASE
         WHEN ts.origin IS NULL OR ts.origin = 'native' THEN 'сессия Mini App (native/null)'
         WHEN ts.origin = 'legacy_backfill' AND w.id IS NULL THEN 'копия без legacy-строки'
         WHEN ts.origin = 'legacy_backfill' AND w.status <> 'completed' THEN 'копия незавершённой тренировки'
         WHEN ts.origin = 'legacy_backfill' AND u.onboarding_completed_at IS NULL THEN 'копия: пользователь без онбординга'
         ELSE 'другое: ' || ts.origin
       END AS reason
FROM training_sessions ts
LEFT JOIN workouts w ON ts.origin = 'legacy_backfill' AND w.id = ts.legacy_id
LEFT JOIN users u ON u.id = w.user_id
WHERE ts.source <> 'elective'
  AND NOT coalesce(ts.origin = 'legacy_backfill' AND w.status = 'completed' AND u.onboarding_completed_at IS NOT NULL, false)
ORDER BY ts.created_at
LIMIT 50;
-- 4) Завершённые тренировки онбордившихся пользователей без копии (должно быть пусто).
SELECT w.id AS workout_id, w.user_id, w.performed_at
FROM workouts w JOIN users u ON u.id = w.user_id
WHERE w.status = 'completed' AND u.onboarding_completed_at IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM training_sessions ts WHERE ts.origin = 'legacy_backfill' AND ts.legacy_id = w.id);
ROLLBACK;
