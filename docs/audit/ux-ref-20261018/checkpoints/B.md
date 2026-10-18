# Checkpoints — executor B (ux/b-nav-electives)

## CP1 — types, mock layer, skeleton
- UTC: see commit. Changed: `apiV2.ts` (contract types, optional), `planRows.ts` (+ `tests/planRows.test.ts`, 7 pass), `e2e/fixtures/contractMock.ts` (Playwright route enrichment until A lands; `E2E_REAL_CONTRACT=1` disables), `e2e/scenarios/ux-b-plan-electives.spec.ts` (fixme skeleton).
- Tests: `node --test tests/planRows.test.ts` green; `tsc -b` green.
- Active ~20 min, waiting ~2 (npm ci), rework none.
- Next: wire plan rows (DashboardScreen), course card, electives entries, seeds.

## CP2 — plans rows, course card, electives, seeds, E2E green
- Changed: `planRows.ts` (start_allowed single source, `isRowStartable`: course rows strictly by start_allowed, own rows keep «Ещё раз»), `DashboardScreen.tsx` (rows: «Объём (А) · занятие N из M», «Доступно с <дата>» / «Не уместится на этой неделе» / «Выполнено», no «Начать» when not allowed; course card + week header schedule note; electives line; rest-day banner; ElectiveScreen mounted from plans), `HomeScreen.tsx` («+» → «Факультатив», per-program inclusion schedule), `ProgramDetailScreen.tsx` (after add: «Открыть мой план», schedule, electives; Latin A/B in catalogue copy normalised via `normalizeBlockLetters`), `SessionPreScreen.tsx` (blocked: «откроется <дата>» + «Сделать факультатив» + «Вернуться в план»; removed «Перейти в обычную "Тренировку"»), `ElectiveEntry.tsx` (new), css (only `.ux-b-*`, `.plans-row-variant`), seeds `ux_b_no_course` / `ux_b_legacy` (CONTRACT §5 shape; ids 940201–940204) + `e2e_seed_all.sh`.
- Existing specs adjusted for the intended new behaviour (not owned paths, minimal): `plans-row-narrow` (label «Не уместится…»), `program-journey-v56` (no «Начать» on rows that cannot start; «А и Б по очереди»).
- Tests: `node --test tests/*.test.ts` 360 pass; `tsc -b && vite build` green; `ux-b-plan-electives.spec.ts` 4/4 green (mock layer); fix proof: with `isStartAllowed` forced true, spec (b) fails. Wider chromium project: no regressions attributable to B after reseed (remaining failures are env: `Dashboard` admin tab needs ADMIN_IDS on server).
- Active ~120 min, waiting ~25 (seed_all, full E2E), rework ~15 (id collision with home_discovery seeds 940001/2 → moved to 9402xx; own-row «Ещё раз» regression caught by session-summary-exit).
- Next: final report. Contract request: none needed. Note for integration: row variant/ordinal in screenshots are mock-derived; A's real values replace them.
