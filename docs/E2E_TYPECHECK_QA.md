# Functional E2E typecheck maintenance

Base: `origin/main` at `44ab6a1e00fe2bb907139d4ceb50f0b8c771d425`.
This maintenance is independent of the frozen release and held PR #389.

## Regression and repairs

On the unchanged base, from `webapp-frontend`:

```sh
npx tsc --project e2e/tsconfig.json --noEmit
```

Exit 2, exactly seven diagnostics:

| File and line | Diagnostic |
| --- | --- |
| `audit-7500c37-fixes.spec.ts:104` | TS2488: NodeList lacks iterator |
| `live-engine-narrow.spec.ts:31` | TS2488: NodeList lacks iterator |
| `live-engine-narrow.spec.ts:132` | TS2488: NodeList lacks iterator |
| `parity/a11y-followup.spec.ts:76` | TS2339: Node has no remove |
| `parity/analytics-distribution.spec.ts:84` | TS2488: NodeList lacks iterator |
| `parity/background-timer.spec.ts:59` | TS2551: EventTarget lacks release |
| `parity/visual-home-detail.spec.ts:36` | TS2488: NodeList lacks iterator |

Add the standard `DOM.Iterable` library for browser NodeList iteration. Keep the
test wake-lock sentinel's existing `release(): Promise<void>` method in its array
element type. Remove the injected style through the Node parent/child API accepted
by Playwright's Node handle. Application code, formulas and schemas are untouched;
strict checking, included files and compiler diagnostics are retained.

The existing E2E workflow installs E2E dependencies, runs `npm run typecheck`, then
installs/starts browsers. Its main browser step explicitly requires a successful
typecheck while retaining execution after a peer-insights test failure.

## Local evidence

- `(cd webapp-frontend/e2e && npm run typecheck)`: exit 0, zero diagnostics.
- Temporarily restore just the three repaired files from the base, leaving the
  new command/workflow intact: exit 2 with exactly seven original diagnostics.
  Restore the repairs and rerun: exit 0, zero diagnostics.
- `(cd webapp-frontend/e2e && npm test -- --list)`: exit 0; 612 tests in 91 files
  discovered. This is collection/static validation, not a browser test pass.
- `(cd webapp-frontend && npm run build)`: passed (`tsc -b` and Vite; existing
  large-chunk advisory remains).
- Parse workflow with PyYAML and assert dependency/typecheck/browser ordering,
  command and the main browser step's successful-typecheck guard: passed.
- `git diff --check`: passed.

A local browser-only fixture probe could not launch: the default Playwright
headless shell is absent, and system Chromium exits on the sandbox's denied
`setsockopt` syscall. No browser/API scenario success is claimed. No API process or
synthetic database was started, and no additional API mocks were introduced.
Full backend/format/build/E2E gates remain required in the draft PR's CI; the full
3000+ local backend suite was not repeated for this test/config-only maintenance.
