# Checkpoints — executor C (UX-03/04/14/17)

## CP1 — 11:08Z — failing tests reproducing UX-03/04/14/17
- Root causes found: (UX-03) session detail and activity card use `formatDurationHm` (ч:мм) -> 30 с shows «0:00»; Summary uses m:ss; no shared display function. (UX-04) Analytics reps panel excludes the max/AMRAP set (53 · 8) while Journal card sums all sets (60 · 9); max set only in a separate panel without total. (UX-17) Summary counts blocks. (UX-14) Journal card already has a time branch; the seeded «Планка» sessions have no set logs at all (seed artefact) - will show session duration instead of dashes when sets are missing.
- Tests added (failing): `webapp-frontend/tests/sessionMetrics.test.ts` (module missing), `tests/test_training_analytics.py::test_amrap_session_totals_match_journal_card` (AMRAP 53+7=60, 8+1=9).
- Active minutes: ~15. Waiting: ~1. Rework: none. Next: sessionMetrics.ts, wire into detail/summary/journal/analytics, backend total for max panel.
