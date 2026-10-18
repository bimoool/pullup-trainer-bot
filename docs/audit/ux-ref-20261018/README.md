# UX reference audit — 2026-10-18

Gate: `docs/AGENT_EXECUTION_MODEL.md` § *Reference audit to implementation gate* (PR #340).
Status: **both sides observed, two passes done** (cloud pass: our side; local pass: real Crimpd 8.5.3 on an Android emulator + ours on an isolated stand). Backlog UX-01…UX-31, sprint plan v2 awaits owner review; no implementation started.

| File | Content |
|---|---|
| `INVENTORY.md` | access inventory (cloud blocker + local resolution), environment, limits |
| `REFERENCE.md` | **real Crimpd** observed journeys (create plan, add workouts, weeks, day placement, same-day repeat, move/delete, execute, history) |
| `COMPARISON.md` | reference vs ours per journey |
| `DECISIONS.md` | cloud questions checked against requirements + the one open list (Q1, Q2) |
| `PASS2-LOCAL.md` | second pass of the local session |
| `reference/` | reference evidence: screens (downscaled), full-text dumps, raw step log, test-data ledger, adb helpers |
| `artifacts-local/`, `harness-local/` | our-side local-pass evidence and scripts (isolated Docker stand, port 8012) |
| `SCENARIOS.md` | scenario map (reference journeys ↔ ours) |
| `BACKLOG.md` | single evidence backlog (stable IDs `UX-NN`) |
| `PASS2.md` | second pass: rechecks, missing states, dedupe |
| `SPRINTS.md` | proposed scenario sprints (for owner review; no implementation before review) |
| `harness/` | Playwright scripts that produced every artifact (re-runnable) |
| `artifacts/` | screenshots + step logs (`<script>.log`) |

Evidence tags: **OBSERVED** (seen in this audit, artifact linked) · **INFERRED** (deduced from code/
behaviour) · **UNKNOWN** · **HISTORICAL** (secondhand note in the repo, not verified against the
reference — a hypothesis, never acceptance evidence).
