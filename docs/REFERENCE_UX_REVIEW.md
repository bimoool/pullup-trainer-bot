# Reference UX review workflow (Crimpd ↔ our Mini App)

Repeatable, black-box process for comparing a Crimpd state with the equivalent screen of our app.
Crimpd is a **product/interaction reference only** — never copy pixels, assets or copy verbatim, never
decompile or patch it, never touch pre-existing personal data (test data: prefix `REF TEST -`, remove
only what you created). Sanitized reference: `~/android-ref-lab/CRIMPD_PRODUCT_REFERENCE.md`,
`FLOW_INDEX.md`, `SCREEN_INDEX.md`, `REF_2_1/screens_shareable/` (raw screenshots stay local).

## 1. Pair the states

Give each comparison a stable **pair id** `<area>-<state>`, e.g. `builder-reps-config`,
`workout-detail`, `live-set-running`. Record the pair in the table in §5.

## 2. Capture the reference (Android emulator lab)

```bash
source ~/android-ref-lab/env.sh
~/android-ref-lab/snap.sh <pair-id>      # screenshot + uiautomator dump → screens/, dumps/
```
Navigate by tapping in the emulator (see `RECIPE.md`); use uiautomator XML as the
"hierarchy" (labels, clickable/enabled flags, bounds). Do not commit raw captures; sanitized
copies go under `REF_2_1/`.

## 3. Capture ours (staging or local)

Local stack: see `webapp-frontend/e2e/README.md` (Postgres, migrations, `npm run build`, uvicorn with
`BOT_TOKEN=e2e-test-token`), then:

```bash
scripts/ux_capture.sh <label> [outdir]     # label e.g. before | after | pr-123
```
Runs `webapp-frontend/e2e/scenarios/ux-capture.spec.ts` at 390 and 320 px (re-seeding per width) and
writes `<outdir>/<label>/<width>/<NN_name>.png` plus `<NN_name>.txt` (visible text + list of
buttons/inputs — our equivalent of the uiautomator dump). Add a screen by adding one `shot(...)` call.
Naming: `NN_` order prefix + snake_case state; reference files use the same pair id.

## 4. Compare — rubric

For each pair answer, per side, with an evidence tag **OBSERVED** (seen in screenshot/dump),
**INFERRED** (deduced, say from what), **UNKNOWN** (not enough evidence — capture more or leave):

1. Hierarchy: what is read first, second?
2. Controls & CTA: where is the primary action; is there exactly one?
3. Editable affordance: can a user tell what is editable without tapping (border/stepper/unit/label)?
4. Obvious without explanation: could a new user say what each row means?
5. Navigation: Back/close behaviour, state preserved?
6. Language: any technical words (enums, raw numbers like `30.00`, IDs)?
7. Layout at 320 / 390: wrapping, CTA visible, bottom-nav overlap, horizontal scroll.

## 5. Classify every difference

| Class | Meaning | Action |
|---|---|---|
| GOOD DIFFERENCE (A) | We differ intentionally, for a valid product reason | Document the reason |
| UX GAP (B) | Ours is less understandable/obvious | Fix or defer with reason |
| DATA-MODEL DIFFERENCE (C) | Reference feature does not map to our backend | Do not fake it; note it |
| UNKNOWN (D) | Insufficient evidence | Capture more |

Record as: `pair id | reference (OBSERVED…) | ours | class | verdict`. Keep the running list in a
short `docs/UX_REFERENCE_AUDIT.md`-style file; close each gap as FIXED / INTENTIONAL DIFFERENCE /
DEFERRED / BLOCKED. "Looks similar" is not a verdict — the user journey must be understandable.

## 6. Guardrails

- Automation is limited to capturing our own app and to the emulator lab you already have; no scraping
  of proprietary assets, no automated visual-diff AI.
- Behavioural checks belong in Playwright specs (`builder-ux.spec.ts` is the pattern) and pure
  formatting/validation in `webapp-frontend/tests/*.test.ts` (`npm run test:unit`).
