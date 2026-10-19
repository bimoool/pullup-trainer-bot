BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '15s';
-- Candidate active legacy STEP users, with personal effective preferences.
SELECT pi.id AS inclusion_id, tp.user_id,
       coalesce(nullif(u.rest_seconds_block_a,0),240) AS expected_a,
       coalesce(nullif(u.rest_seconds_block_b,0),180) AS expected_b,
       coalesce(nullif(u.big_break_seconds,0),900) AS expected_gap
FROM program_inclusions pi
JOIN training_plans tp ON tp.id=pi.training_plan_id
JOIN users u ON u.id=tp.user_id
WHERE pi.is_active
  AND pi.snapshot->>'progression_strategy_type'='step'
  AND coalesce(pi.progression_state->>'program_version','') <> 'pullups_v5_6'
ORDER BY tp.user_id, pi.id;
-- Persisted native live sessions: inspect recipe/engine-plan by block (no backfill doubles).
SELECT s.id, s.user_id, s.status, s.engine_status, s.engine_version, s.created_at,
       s.program_inclusion_id, b.ordinality AS block_position,
       b.value->'sets'->0->>'rest_after_seconds' AS engine_first_rest,
       b.value->>'rest_after_block_seconds' AS engine_gap,
       s.prescription_snapshot->'blocks'->((b.ordinality-1)::int)->'sets'->0->>'rest_after_seconds'
         AS prescribed_first_rest
FROM training_sessions s
JOIN program_inclusions pi ON pi.id=s.program_inclusion_id
CROSS JOIN LATERAL jsonb_array_elements(coalesce(s.engine_plan->'blocks','[]'::jsonb))
  WITH ORDINALITY b(value,ordinality)
WHERE s.origin='native' AND s.client_session_id IS NOT NULL
  AND pi.snapshot->>'progression_strategy_type'='step'
  AND coalesce(pi.progression_state->>'program_version','') <> 'pullups_v5_6'
ORDER BY s.created_at DESC, s.id, b.ordinality;
ROLLBACK;
-- Count of ACTIVE native legacy-STEP sessions with a 90s plan.
BEGIN TRANSACTION READ ONLY;
SELECT count(*) AS active_with_90s, count(DISTINCT s.user_id) AS users
FROM training_sessions s
JOIN program_inclusions pi ON pi.id=s.program_inclusion_id
WHERE s.engine_status='active' AND s.origin='native' AND s.engine_version=2
  AND pi.snapshot->>'progression_strategy_type'='step'
  AND coalesce(pi.progression_state->>'program_version','') <> 'pullups_v5_6'
  AND s.engine_plan->'blocks'->0->'sets'->0->>'rest_after_seconds'='90';
ROLLBACK;
