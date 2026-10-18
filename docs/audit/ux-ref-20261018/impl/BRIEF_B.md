RUN MODE: LOCAL CODE
MODEL: STANDARD / SONNET
MODEL REASON: frontend wiring on existing screens with a fixed API contract; UI copy decisions are pre-made in the audit
SESSION: NEW
TASK TYPE: IMPLEMENTATION
BASE SHA: e2ed40e5da46e8a2a743fd4a69f0f9e9b4d1d8e0 (main); campaign tip b769de6 (+ contract commit)
BRANCH / WORKTREE: `ux/b-nav-electives` / `/Users/kirillv./Documents/Claude Code/pullup-ux-b`
ACCESS: git, Docker, shared venv (for local E2E stack), npm (network). Unverified: real Telegram client rendering.
DELIVERABLE: pushed branch with the Mini App changes below + E2E specs + screenshots; checkpoint file `checkpoints/B.md`
TIMEBOX: first checkpoint ≤ 15 min; expected 2–3.5 days of active work, in pushed slices
NEXT STATUS: first checkpoint pushed within 15 min of start
AUTHORIZED ACTIONS: edit owned files, run focused tests/E2E, commit, push own branch. No merge, no deploy.

# Task B — navigation, А/Б, old 3-per-week explanation, visible free electives (UX-06, 08, 09, 32, 33)

Path to close: **course card → «Открыть мой план» → rows named А/Б with honest states → the available workout starts (or says exactly when) → free electives are found and used.**
Read: backlog UX-01/02/06/08/09/20/32/33, `COMPLAINTS.md` §1–2, `CONTRACT_A_B.md` (v1), `webapp-frontend/src/App.tsx` header comments (issue #175), `ElectiveScreen.tsx`.

## You own
`webapp-frontend/src/` — `HomeScreen.tsx`, `DashboardScreen.tsx`, `DashboardV2Screen.tsx`, `SessionPreScreen.tsx` (copy of blocked states + removing the «Перейти в обычную "Тренировку"» dead-end), `App.tsx` (routing only), the programme detail/card screens, `apiV2.ts` (**only** the plan/inclusion/elective types and fetchers), `index.css`/`screens-secondary.css` (only classes you add), `e2e/scenarios/ux-b-*.spec.ts` (new), `scripts/e2e_seed.py` / `scripts/e2e_seed_all.sh` (additions only: a legacy-snapshot user per CONTRACT §5).
**Do not edit** backend (`app/**`) — need a field? `checkpoints/B-contract-request.md`; Journal/Analytics/Session summary screens (C).

## Work (suggested slices; push each)
1. **Mocks first (≤ 15 min checkpoint):** add TypeScript types for the new contract fields (optional in the type until A lands); a typed mock layer/fixture for E2E so you can build without waiting. Write the E2E spec skeleton for the journey (fresh user and owner-shaped legacy user).
2. **Plans rows (UX-01/02/08/09/20):** show «Начать» iff `start_allowed`; if `blocked_reason == "too_early"` show «Доступно с <дата>» (no button); `infeasible` → «Не уместится на этой неделе» (no button); `completed` → done state. Name rows by `session_variant` («Объём · А» / «Сила · Б», the catalogue spelling) and `session_ordinal` («занятие 2 из 3»); one spelling А/Б across Home, program detail, plan, pre-start (fix UX-09 copy). Remove every path from the plan that ends on a «нельзя» screen; keep `SessionPreScreen` blocked-state copy only as a fallback with a real next action (plan / when it opens).
3. **Course card + programme detail (UX-06/32):** after «Добавить в план» → «Открыть мой план» / «Начать»; the course card and the plan header show the schedule in words from `inclusion.schedule` — for `is_legacy && sessions_per_week == 3`: «Расписание вашей версии курса: 3 занятия в неделю» plus the honest consequence when `weekly_capacity < sessions_per_week` («не все уместятся из-за отдыха между тренировками»). **No «switch to 2» button** (out of scope).
4. **Electives (UX-33):** visible entry in three places — course card («Факультативы: {entries_this_week} из {elective_limit} на этой неделе»), the rest-day state of the plan («Сегодня отдых — можно факультатив»), Home «+» menu — all open the existing `ElectiveScreen` (mount it from the new context; do not resurrect the legacy tab). One line of explanation: free, up to 2 per week, does not affect progression. Limit reached → explicit text, not a hidden button. No subscription gate.
5. **Integration:** screenshots light/dark/320; E2E: (a) fresh profile: connect course → «Открыть мой план» → rows → start; (b) legacy-shaped user: «1 из 3», explanation visible, blocked rows say when; (c) electives reachable in ≤ 2 taps from the card and from the rest-day state, submit works, Journal shows it, weekly counter updates, limit message on the third.

## Acceptance
`npx tsc -b && npx vite build` green; your Playwright specs green against a local stack (ports 8031–8039; see `webapp-frontend/e2e/README.md` and `docs/STAGING_QA_HARNESS.md`); screenshots saved to `docs/audit/ux-ref-20261018/checkpoints/B-shots/` (small PNGs); only owned paths changed; with contract mocks the UI is complete even before A lands (A's real fields replace mocks at integration).
