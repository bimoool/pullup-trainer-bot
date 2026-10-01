# Current task brief

<!-- Written by the planner (scripts/orch.py). Exactly one active brief. The worker reads
     it; only the planner / finish step rewrites it. -->

ISSUE: #250
TITLE: Cover workout editor behavior with a mobile keyboard viewport
URL: https://github.com/bimoool/pullup-trainer-bot/issues/250
PRIORITY: p1
TYPE: qa
BASE BRANCH: develop/current
BASE SHA: 17c6b648d04995c62e3ce2025c2afee687be70aa
BRANCH: orch/issue-250
BATCH: 5 (task 2/5)
SELECTED AT: 2026-10-01 05:20 UTC

## Goal

Keep workout-editor fields and save controls reachable when the mobile keyboard reduces the Mini App viewport.

## Acceptance criteria

- [ ] Add a focused mobile E2E scenario that opens the workout editor, focuses name and protocol inputs, and simulates a keyboard-sized viewport-height reduction.
- [ ] The focused field and the next/save action can be scrolled into view and remain operable at 320px and 390px widths.
- [ ] Restoring the viewport returns the layout without stale offsets or horizontal overflow.
- [ ] Fix deterministic CSS/layout defects exposed by the scenario without redesigning the editor.
- [ ] Keep runtime bounded; do not duplicate the full E2E suite for this check.
- [ ] No production deploy or merge to `main`.

## Files / areas

Workout editor/builder screens, mobile layout CSS, and a focused Playwright scenario.

## Tests required

Focused Playwright coverage at 320px and 390px, existing frontend unit tests, and the normal build.

Always: `ruff check app/ tests/ scripts/`, `pytest -q`; frontend touched → `npm run build && npm run test:unit` in `webapp-frontend/`.

## Do not touch

- `main` — never merge, never push
- production deploy (`deploy.yml`) — never run
- `.github/workflows/**`, `.github/orch/**`, `.github/task/**`, `docs/PROJECT_STATUS.md`
- destructive / non-additive Alembic migrations
- secrets, tokens, `.env*`
- other issues' scope — no drive-by features
- issue 'Out of scope': Native keyboard language behavior, Dynamic Type, visual redesign, or product copy changes.

## Stop conditions

- acceptance criteria ambiguous or contradict PROJECT_SPEC/constitution → VERDICT needs-owner
- task needs a product/security decision, credentials, prod, real device → VERDICT needs-owner
- tests cannot be made green within scope → VERDICT blocked (push what exists, explain)
- scope turns out to be >1 task → do the first coherent part, VERDICT blocked with split proposal
