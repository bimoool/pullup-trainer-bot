-- TEST HARNESS INJECTION: time travel for audit_returning_week_transition (tg 7300003, user_id=1 / plan 1).
-- Real backfill (run with now=-10d) created PlanWeek of the previous week; the 2nd real backfill run
-- (operator re-run, needed for other users) also materialised the CURRENT week. We remove only that
-- current-week materialisation so that the first app open must perform the week transition itself.
-- Before: plan_weeks id1 (week -1, 2026-09-21), id2 (week 1, 2026-10-05); plan_items 3,4 belong to id2.
DELETE FROM plan_items WHERE plan_week_id IN (SELECT id FROM plan_weeks WHERE training_plan_id=1 AND start_date='2026-10-05');
DELETE FROM plan_weeks WHERE training_plan_id=1 AND start_date='2026-10-05';
