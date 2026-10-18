// Платформа, в которой открыт интерфейс: Mini App внутри Telegram или обычный браузер (WEB-кампания).
// Владелец файла — координатор. Экраны читают режим через usePlatform(); сам режим выставляет только App.tsx
// по результату resolveAuth() (platform/authBootstrap.ts).
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

export type PlatformMode = "telegram" | "browser";

export type PlatformValue = {
  mode: PlatformMode;
  /** Выход из браузерной сессии (в Telegram — undefined: Mini App не «выходит»). Реализует WEB-AUTH. */
  signOut?: () => void;
};

type PlatformState = PlatformValue & { setMode: (mode: PlatformMode) => void };

const PlatformContext = createContext<PlatformState>({ mode: "telegram", setMode: () => {} });

export function PlatformProvider({ children, signOut }: { children: ReactNode; signOut?: () => void }) {
  const [mode, setMode] = useState<PlatformMode>("telegram");
  const value = useMemo(() => ({ mode, signOut: mode === "browser" ? signOut : undefined, setMode }), [mode, signOut]);
  return <PlatformContext.Provider value={value}>{children}</PlatformContext.Provider>;
}

/** Режим и выход: для оболочки, навигации и экранов, которым важно, где они открыты. */
export function usePlatform(): PlatformValue {
  const { mode, signOut } = useContext(PlatformContext);
  return { mode, signOut };
}

/** Только App.tsx: выставить режим после определения способа входа. */
export function usePlatformSetter(): (mode: PlatformMode) => void {
  return useContext(PlatformContext).setMode;
}
