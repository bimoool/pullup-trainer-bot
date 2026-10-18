// Оболочка интерфейса. Владелец — WEB-LAYOUT (до его работы — ровно прежняя разметка Mini App).
// DOM-контракт e2e: корень .app-shell (+ .app-shell-with-nav при нижней навигации).
import type { ReactNode } from "react";

export function AppShell({ withNav, children }: { withNav: boolean; children: ReactNode }) {
  return <div className={withNav ? "app-shell app-shell-with-nav" : "app-shell"}>{children}</div>;
}
