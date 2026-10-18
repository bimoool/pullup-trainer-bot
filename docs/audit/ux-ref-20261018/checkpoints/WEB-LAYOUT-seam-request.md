# WEB-LAYOUT seam request (to coordinator)

**What:** `webapp-frontend/src/App.tsx`, the `if (v2Session !== null)` branch (~line 416) and the `state.status === "loading"` branch (~line 370) return a raw `<div className="app-shell">...</div>`. Replace the wrapper with `<AppShell withNav={false}>...</AppShell>` (same children).

**Why:** in browser mode the in-page «Назад» control, the sign-out button and the confirm sheet (`ConfirmHost`) are rendered by `AppShell`. The whole live-session flow (plan -> session pre-screen -> live workout -> summary) bypasses it, so there is no in-page back from the pre-screen (`useBackButton(onGoToWorkout)` registers fine but nothing renders the control) and `confirmAction` has no host there (the promise never resolves). In `telegram` mode `AppShell` renders exactly `<div className="app-shell">{children}</div>`, so Mini App output is byte-identical.

**Exact change:**
```tsx
  if (v2Session !== null) {
    return (
-      <div className="app-shell">
+      <AppShell withNav={false}>
         <PlanSessionFlow ... />
-      </div>
+      </AppShell>
```
The e2e spec `layout-flows.spec.ts` «План -> предэкран сессии -> Назад» fails until this is applied.
