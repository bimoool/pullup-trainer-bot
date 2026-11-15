WITH session_facts AS (
    SELECT s.*,
        EXISTS (SELECT 1 FROM session_events e WHERE e.session_id=s.id) AS has_events,
        EXISTS (SELECT 1 FROM session_plan_items l WHERE l.session_id=s.id) AS has_links,
        EXISTS (SELECT 1 FROM session_blocks b LEFT JOIN exercises e ON e.id=b.exercise_id
            WHERE b.session_id=s.id AND (b.complex_id IS NOT NULL OR e.id IS NULL
                OR e.subcategory IN ('block_a','block_b')
                OR (e.source_type='user' AND e.owner_user_id IS DISTINCT FROM s.user_id)
                OR (e.source_type='system' AND e.owner_user_id IS NOT NULL)
                OR e.source_type NOT IN ('system','user'))) AS unsafe_blocks,
        COALESCE((s.engine_status IS NULL AND s.engine_plan IS NULL AND s.engine_state IS NULL
            AND s.engine_version IS NULL
            AND NOT EXISTS (SELECT 1 FROM session_events e WHERE e.session_id=s.id)), false) AS no_engine,
        COALESCE((s.workout_definition_id IS NOT NULL
            AND EXISTS (SELECT 1 FROM complexes c WHERE c.id=s.workout_definition_id
                AND ((c.source_type='user' AND c.owner_user_id=s.user_id)
                    OR (c.source_type='system' AND c.owner_user_id IS NULL)))
            AND (s.workout_definition_version_id IS NULL OR EXISTS (
                SELECT 1 FROM workout_definition_versions v WHERE v.id=s.workout_definition_version_id
                    AND v.workout_definition_id=s.workout_definition_id))
            AND jsonb_typeof(s.prescription_snapshot)='object'
            AND s.prescription_snapshot->>'snapshot_schema'='2'
            AND s.prescription_snapshot->>'workout_definition_id'=s.workout_definition_id::text
            AND (s.prescription_snapshot->>'workout_definition_version_id')
                IS NOT DISTINCT FROM s.workout_definition_version_id::text
            AND jsonb_typeof(s.prescription_snapshot->'blocks')='array'
            AND jsonb_typeof(s.prescription_snapshot->'provenance')='object'
            AND s.prescription_snapshot#>>'{provenance,kind}'='static'
            AND s.prescription_snapshot#>>'{provenance,program_inclusion_id}' IS NULL
            AND s.prescription_snapshot#>>'{provenance,course_program}' IS NULL
            AND (s.workout_snapshot IS NULL OR (jsonb_typeof(s.workout_snapshot)='object'
                AND s.workout_snapshot->>'workout_id'=s.workout_definition_id::text
                AND jsonb_typeof(s.workout_snapshot->'items')='array'))), false) AS saved_definition,
        COALESCE((s.engine_version=1 AND s.engine_status IS NULL
            AND s.engine_plan IS NULL AND s.engine_state IS NULL
            AND NOT EXISTS (SELECT 1 FROM session_events e WHERE e.session_id=s.id))
            OR (s.engine_version=2 AND s.engine_status='completed'
                AND jsonb_typeof(s.engine_plan)='object'
                AND jsonb_typeof(s.engine_plan->'blocks')='array'
                AND jsonb_array_length(CASE WHEN jsonb_typeof(s.engine_plan->'blocks')='array'
                    THEN s.engine_plan->'blocks' ELSE '[]'::jsonb END)>0
                AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(
                    CASE WHEN jsonb_typeof(s.engine_plan->'blocks')='array'
                        THEN s.engine_plan->'blocks' ELSE '[]'::jsonb END) b
                    WHERE jsonb_typeof(b) IS DISTINCT FROM 'object'
                        OR NOT COALESCE(b->>'kind' IN ('sets','interval'), false)
                        OR jsonb_typeof(b->'prep_seconds') IS DISTINCT FROM 'number'
                        OR NOT COALESCE(b->>'prep_seconds' ~ '^[0-9]+$', false)
                        OR (COALESCE(b->'rest_after_block_seconds', 'null'::jsonb)<>'null'::jsonb
                            AND (jsonb_typeof(b->'rest_after_block_seconds') IS DISTINCT FROM 'number'
                                OR NOT COALESCE(b->>'rest_after_block_seconds' ~ '^[0-9]+$', false)))
                        OR (b->>'kind'='sets' AND (jsonb_typeof(b->'sets') IS DISTINCT FROM 'array'
                            OR jsonb_array_length(CASE WHEN jsonb_typeof(b->'sets')='array'
                                THEN b->'sets' ELSE '[]'::jsonb END)=0))
                        OR (b->>'kind'='sets' AND EXISTS (SELECT 1 FROM jsonb_array_elements(
                            CASE WHEN jsonb_typeof(b->'sets')='array' THEN b->'sets' ELSE '[]'::jsonb END) t
                            WHERE jsonb_typeof(t) IS DISTINCT FROM 'object'
                                OR NOT COALESCE(t->>'kind' IN ('reps','max_reps','time','max_time'), false)
                                OR (t->>'kind'='time' AND (jsonb_typeof(t->'target') IS DISTINCT FROM 'number'
                                    OR NOT COALESCE(t->>'target' ~ '^[1-9][0-9]*$', false)))
                                OR (COALESCE(t->'rest_after_seconds', 'null'::jsonb)<>'null'::jsonb
                                    AND (jsonb_typeof(t->'rest_after_seconds') IS DISTINCT FROM 'number'
                                        OR NOT COALESCE(t->>'rest_after_seconds' ~ '^[0-9]+$', false)))))
                        OR (b->>'kind'='interval' AND (jsonb_typeof(b->'interval') IS DISTINCT FROM 'object'
                            OR EXISTS (SELECT 1 FROM unnest(ARRAY['work_seconds','rest_seconds','rounds']) k
                                WHERE jsonb_typeof(b->'interval'->k) IS DISTINCT FROM 'number'
                                    OR NOT COALESCE(b->'interval'->>k ~ '^[0-9]+$', false))
                            OR NOT COALESCE(b#>>'{interval,work_seconds}' ~ '^[1-9][0-9]*$', false)
                            OR NOT COALESCE(b#>>'{interval,rounds}' ~ '^[1-9][0-9]*$', false))))
                AND jsonb_typeof(s.engine_state)='object'
                AND s.engine_state->>'engine_version'='2'
                AND s.engine_state->>'status'='completed'
                AND s.engine_state->>'phase'='COMPLETE'
                AND jsonb_typeof(s.engine_state->'cursor')='object'
                AND jsonb_typeof(s.engine_state#>'{cursor,block_index}')='number'
                AND jsonb_typeof(s.engine_state#>'{cursor,set_index}')='number'
                AND s.engine_state#>>'{cursor,block_index}' ~ '^[0-9]+$'
                AND s.engine_state#>>'{cursor,set_index}' ~ '^[0-9]+$'
                AND s.engine_state#>'{cursor,block_index}' <= '32767'::jsonb
                AND s.engine_state#>'{cursor,set_index}' <= '32766'::jsonb
                AND EXISTS (SELECT 1 FROM jsonb_array_elements(
                    CASE WHEN jsonb_typeof(s.engine_plan->'blocks')='array'
                        THEN s.engine_plan->'blocks' ELSE '[]'::jsonb END) WITH ORDINALITY b(block,position)
                    WHERE to_jsonb(b.position-1)=s.engine_state#>'{cursor,block_index}'
                        AND ((b.block->>'kind'='sets' AND s.engine_state#>'{cursor,set_index}'
                            < to_jsonb(jsonb_array_length(CASE WHEN jsonb_typeof(b.block->'sets')='array'
                                THEN b.block->'sets' ELSE '[]'::jsonb END)))
                            OR (b.block->>'kind'='interval'
                                AND s.engine_state#>'{cursor,round_index}' < b.block#>'{interval,rounds}'
                                AND s.engine_state#>'{cursor,set_index}'=s.engine_state#>'{cursor,round_index}')))
                AND s.engine_state->'cursor' ? 'round_index'
                AND (s.engine_state#>'{cursor,round_index}'='null'::jsonb
                    OR (jsonb_typeof(s.engine_state#>'{cursor,round_index}')='number'
                        AND s.engine_state#>>'{cursor,round_index}' ~ '^[0-9]+$'))
                AND jsonb_typeof(s.engine_state->'logs')='array'
                AND jsonb_array_length(CASE WHEN jsonb_typeof(s.engine_state->'logs')='array'
                    THEN s.engine_state->'logs' ELSE '[]'::jsonb END)>0
                AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(
                    CASE WHEN jsonb_typeof(s.engine_state->'logs')='array'
                        THEN s.engine_state->'logs' ELSE '[]'::jsonb END) l
                    WHERE jsonb_typeof(l) IS DISTINCT FROM 'object'
                        OR NOT (l ?& ARRAY['log_index','block_index','set_index','round_index','is_extra','value','effort','note'])
                        OR EXISTS (SELECT 1 FROM unnest(ARRAY['log_index','block_index','set_index']) k
                            WHERE jsonb_typeof(l->k) IS DISTINCT FROM 'number'
                                OR NOT COALESCE(l->>k ~ '^[0-9]+$', false))
                        OR l->'block_index' >= to_jsonb(jsonb_array_length(
                            CASE WHEN jsonb_typeof(s.engine_plan->'blocks')='array'
                                THEN s.engine_plan->'blocks' ELSE '[]'::jsonb END))
                        OR NOT COALESCE(l->'round_index'='null'::jsonb
                            OR (jsonb_typeof(l->'round_index')='number' AND l->>'round_index' ~ '^[0-9]+$'), false)
                        OR jsonb_typeof(l->'is_extra') IS DISTINCT FROM 'boolean'
                        OR NOT COALESCE(jsonb_typeof(l->'value') IN ('number','null'), false)
                        OR NOT COALESCE(jsonb_typeof(l->'effort') IN ('number','null'), false)
                        OR NOT COALESCE(jsonb_typeof(l->'note') IN ('string','null'), false))
                AND NOT EXISTS (SELECT 1 FROM unnest(ARRAY['started_at','ended_at','last_at',
                    'phase_seq','phase_started_at','active_elapsed_ms','phase_active_ms']) k
                    WHERE jsonb_typeof(s.engine_state->k) IS DISTINCT FROM 'number'
                        OR NOT COALESCE(s.engine_state->>k ~ '^[0-9]+$', false))
                AND s.engine_state->'ended_at' >= s.engine_state->'started_at'
                AND s.engine_state->'last_at' >= s.engine_state->'ended_at'
                AND s.engine_state->'phase_started_at'=s.engine_state->'ended_at'
                AND s.engine_state->'phase_deadline_at'='null'::jsonb
                AND s.engine_state->'paused_at'='null'::jsonb
                AND s.engine_state->'active_since'='null'::jsonb
                AND EXISTS (SELECT 1 FROM session_events e WHERE e.session_id=s.id
                    AND e.seq=0 AND e.type='start' AND e.outcome='applied')
                AND EXISTS (SELECT 1 FROM session_events e WHERE e.session_id=s.id
                    AND e.seq>0 AND e.outcome='applied'
                    AND to_jsonb((EXTRACT(EPOCH FROM e.server_at)*1000)::bigint) >= s.engine_state->'ended_at'
                    AND e.type IN ('deadline','skip_wait','submit_result','stop','finish_early','confirm_blocks'))), false) AS terminal_direct_engine
    FROM training_sessions s
), classified_sessions AS (
    SELECT s.*, CASE
        WHEN s.status <> 'completed' THEN 'ACTIVE_OR_INCOMPLETE'
        WHEN s.program_inclusion_id IS NOT NULL OR s.plan_item_id IS NOT NULL OR s.has_links THEN 'LINKED'
        WHEN s.superseded_by_id IS NOT NULL THEN 'SUPERSEDED'
        WHEN s.origin='legacy_backfill' THEN CASE
            WHEN s.no_engine AND s.legacy_id IS NOT NULL
                AND s.superseded_at IS NOT NULL AND s.superseded_reason='legacy_deleted'
                AND EXISTS (SELECT 1 FROM workouts_archive_admin_reset a
                    WHERE a.id=s.legacy_id AND a.user_id=s.user_id
                        AND a.performed_at=s.performed_at AND a.status='completed')
                AND NOT EXISTS (SELECT 1 FROM workouts w WHERE w.id=s.legacy_id)
            THEN NULL ELSE 'LEGACY_UNPROVED' END
        WHEN s.origin IS DISTINCT FROM 'native' THEN 'UNKNOWN_ORIGIN'
        WHEN s.completed_at IS NULL THEN 'ACTIVE_OR_INCOMPLETE'
        WHEN s.legacy_id IS NOT NULL OR s.superseded_at IS NOT NULL THEN 'SUPERSEDED'
        WHEN s.source NOT IN ('freeform','backdated') OR s.source_v2 IS NULL
            OR s.source_v2 NOT IN ('external_activity','manual_custom','manual_existing_workout','direct_live')
            THEN 'UNSUPPORTED_SOURCE'
        WHEN s.unsafe_blocks THEN 'BLOCK_OWNERSHIP_OR_STEP'
        WHEN s.source_v2 IN ('external_activity','manual_custom') THEN CASE
            WHEN NOT s.no_engine THEN 'ENGINE_NOT_TERMINAL'
            WHEN s.workout_definition_id IS NOT NULL OR s.workout_snapshot IS NOT NULL
                OR s.workout_definition_version_id IS NOT NULL THEN 'DEFINITION_OR_SNAPSHOT'
            ELSE NULL END
        WHEN NOT s.saved_definition OR s.kind IS DISTINCT FROM 'strength' THEN 'DEFINITION_OR_SNAPSHOT'
        WHEN s.source_v2='manual_existing_workout' AND NOT s.no_engine THEN 'ENGINE_NOT_TERMINAL'
        WHEN s.source_v2='direct_live' AND (s.source <> 'freeform' OR NOT s.terminal_direct_engine)
            THEN 'ENGINE_NOT_TERMINAL'
        ELSE NULL END AS blocked_reason
    FROM session_facts s
), users_classified AS (
    SELECT u.id, u.onboarding_completed_at IS NOT NULL AS onboarded,
        EXISTS (SELECT 1 FROM training_plans p WHERE p.user_id=u.id) AS has_plan,
        (EXISTS (SELECT 1 FROM workouts w WHERE w.user_id=u.id)
            OR EXISTS (SELECT 1 FROM elective_workouts e WHERE e.user_id=u.id)
            OR EXISTS (SELECT 1 FROM workout_sets s WHERE s.user_id=u.id AND s.workouts_completed>0)) AS current_legacy,
        EXISTS (SELECT 1 FROM classified_sessions s WHERE s.user_id=u.id AND s.blocked_reason IS NOT NULL) AS blocked_session
    FROM users u
), classified AS (
    SELECT *, current_legacy OR blocked_session AS requires_plan FROM users_classified
)
SELECT /*planless-candidate-aggregate*/
    count(*) AS users_total,
    count(*) FILTER (WHERE onboarded) AS users_onboarded,
    count(*) FILTER (WHERE onboarded AND has_plan) AS onboarded_with_plan,
    count(*) FILTER (WHERE onboarded AND NOT has_plan AND NOT requires_plan) AS compatible_onboarded_without_plan,
    count(*) FILTER (WHERE NOT onboarded AND has_plan) AS non_onboarded_with_plan,
    count(*) FILTER (WHERE NOT onboarded AND NOT has_plan AND NOT requires_plan) AS compatible_non_onboarded_without_plan,
    count(*) FILTER (WHERE NOT has_plan AND requires_plan) AS blocked_without_plan,
    (SELECT count(*) FROM training_plans) AS training_plans_total,
    count(*) FILTER (WHERE NOT has_plan AND current_legacy) AS current_legacy,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.blocked_reason='ACTIVE_OR_INCOMPLETE')) AS active_or_incomplete,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.blocked_reason='LINKED')) AS linked,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.blocked_reason='SUPERSEDED')) AS superseded,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.blocked_reason='UNKNOWN_ORIGIN')) AS unknown_origin,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.blocked_reason='UNSUPPORTED_SOURCE')) AS unsupported_source,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.blocked_reason='BLOCK_OWNERSHIP_OR_STEP')) AS block_ownership_or_step,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.blocked_reason='DEFINITION_OR_SNAPSHOT')) AS definition_or_snapshot,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.blocked_reason='ENGINE_NOT_TERMINAL')) AS engine_not_terminal,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.blocked_reason='LEGACY_UNPROVED')) AS legacy_unproved,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.origin='native' AND s.status='completed'
            AND s.source_v2='manual_existing_workout')) AS native_manual_saved,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.origin='native' AND s.status='completed'
            AND s.source_v2='direct_live' AND s.engine_version=1)) AS native_direct_v1,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.origin='native' AND s.status='completed'
            AND s.source_v2='direct_live' AND s.engine_version=2)) AS native_direct_v2,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.origin='native' AND s.status='completed'
            AND s.workout_definition_id IS NOT NULL)) AS native_with_definition,
    count(*) FILTER (WHERE NOT has_plan AND EXISTS (SELECT 1 FROM classified_sessions s
        WHERE s.user_id=classified.id AND s.origin='native' AND s.status='completed'
            AND s.workout_definition_version_id IS NOT NULL)) AS native_with_version
FROM classified
