# WEB-AUTH seam requests (for the coordinator; App.tsx / shell files are not mine)

## 1. Render the sign-out button (needed for the "logout" acceptance item)
Component ready: `webapp-frontend/src/platform/SignOutButton.tsx` (`<SignOutButton />`; renders nothing unless `usePlatform().signOut` exists,
i.e. only in browser mode; `data-testid="sign-out"`; calls `signOutBrowser()` = POST /api/web-auth/logout, clears the persisted query cache, reloads).
Please place it where the browser user can find it: e.g. in `SettingsScreen.tsx` (bottom) or the profile header, and/or the WEB-LAYOUT shell header.
My E2E logout spec uses the button when present (`getByTestId("sign-out")`) and otherwise calls the same endpoint through the page.

## 2. Session lost mid-use in browser mode (App.tsx, `state.status === "error"` block, ~lines 382-393)
Today a 401 shows «Сессия Telegram устарела. Закрой приложение…» with a «Закрыть» button that calls `getWebApp()?.close?.()`
— meaningless in a browser. Requested (App.tsx only):
```tsx
const { mode } = usePlatform();           // or the setter's current mode kept in a ref
...
{isSessionExpiredMessage(state.message) && (
  mode === "browser"
    ? <button type="button" className="action-button" data-testid="session-expired-relogin" onClick={() => window.location.reload()}>Войти заново</button>
    : /* existing «Закрыть» button */
)}
```
(`reload` re-runs `resolveAuth()` → `GET /api/web-auth/session` → `login` screen.) The message text itself may stay (or use a browser variant: «Сессия истекла. Войдите заново.»).
