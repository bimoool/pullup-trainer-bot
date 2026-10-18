// Оболочка интерфейса. Владелец — WEB-LAYOUT.
// DOM-контракт e2e: корень .app-shell (+ .app-shell-with-nav при нижней навигации). В режиме telegram разметка
// ровно прежняя; в браузере добавляется класс app-shell-web, верхняя полоса («Назад», выход) и шторка подтверждения.
import { useEffect, useLayoutEffect, type ReactNode } from "react";

import { BackControl } from "./BackBridge";
import { handleEscape } from "./backStore";
import { ConfirmHost } from "./ConfirmHost";
import { usePlatform } from "./mode";
import { SignOutButton } from "./SignOutButton";
import { setBrowserRuntime } from "./runtime";

export function AppShell({ withNav, children }: { withNav: boolean; children: ReactNode }) {
  const { mode, signOut } = usePlatform();
  const browser = mode === "browser";
  // До первого эффекта потомков: confirmAction / openExternalLink / стек «Назад» читают этот режим.
  useLayoutEffect(() => {
    setBrowserRuntime(browser);
  }, [browser]);
  useEffect(() => {
    if (!browser) {
      return;
    }
    const onKey = (event: KeyboardEvent) => {
      if (handleEscape(event)) {
        event.preventDefault();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [browser]);
  const base = withNav ? "app-shell app-shell-with-nav" : "app-shell";
  if (!browser) {
    return <div className={base}>{children}</div>;
  }
  return (
    <div className={`${base} app-shell-web`}>
      <div className="web-topbar">
        <BackControl />
        {/* одна кнопка: на телефоне справа в верхней полосе, на десктопе (CSS) — внизу боковой навигации */}
        {signOut && <SignOutButton className="web-signout" />}
      </div>
      {children}
      <ConfirmHost />
    </div>
  );
}
