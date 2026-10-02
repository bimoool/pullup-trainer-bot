import { useEffect } from "react";

import { acquireClosingConfirmation } from "./telegramPlatform";

/** Пока `active`, Telegram спрашивает «Закрыть приложение?» вместо молчаливого закрытия (Bot API 6.2+). */
export function useClosingConfirmation(active = true): void {
  useEffect(() => {
    if (!active) {
      return;
    }
    return acquireClosingConfirmation();
  }, [active]);
}
