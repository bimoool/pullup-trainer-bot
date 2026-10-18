# UX reference audit — 2026-10-18

Gate: `docs/AGENT_EXECUTION_MODEL.md` § *Reference audit to implementation gate* (PR #340).
Status: **in progress — pass 1 on our product.** Reference side blocked (see INVENTORY.md).

| File | Content |
|---|---|
| `INVENTORY.md` | access inventory (reference, ours), environment, limits |
| `SCENARIOS.md` | scenario map (reference journeys ↔ ours) |
| `BACKLOG.md` | single evidence backlog (stable IDs `UX-NN`) |
| `PASS2.md` | second pass: rechecks, missing states, dedupe |
| `SPRINTS.md` | proposed scenario sprints (for owner review; no implementation before review) |
| `harness/` | Playwright scripts that produced every artifact (re-runnable) |
| `artifacts/` | screenshots + step logs (`<script>.log`) |

Evidence tags: **OBSERVED** (seen in this audit, artifact linked) · **INFERRED** (deduced from code/
behaviour) · **UNKNOWN** · **HISTORICAL** (secondhand note in the repo, not verified against the
reference — a hypothesis, never acceptance evidence).
