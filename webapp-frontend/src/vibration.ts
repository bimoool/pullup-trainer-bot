// Вибрация на конец фазы таймера (#281, Crimpd R14). Telegram HapticFeedback (WebApp 6.1+),
// запасной путь — navigator.vibrate (Android WebView). Включатель — настройка устройства:
// вибромотор есть не у каждого клиента, поэтому в localStorage, а не в серверных настройках.

const STORAGE_KEY = "pullup.timerVibration";

type HapticApi = {
  notificationOccurred?: (type: "error" | "success" | "warning") => void;
  impactOccurred?: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
};

/** Включено ли (по умолчанию — да). */
export function isVibrationEnabled(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== "off";
  } catch {
    return true;
  }
}

export function setVibrationEnabled(enabled: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, enabled ? "on" : "off");
  } catch {
    // нет localStorage — настройка живёт до перезагрузки только в состоянии экрана
  }
}

/** Один импульс «фаза закончилась». true — сигнал отправлен. */
export function vibratePhaseEnd(): boolean {
  if (!isVibrationEnabled()) {
    return false;
  }
  const haptic = (window as unknown as { Telegram?: { WebApp?: { HapticFeedback?: HapticApi } } })
    .Telegram?.WebApp?.HapticFeedback;
  if (haptic?.notificationOccurred) {
    haptic.notificationOccurred("success");
    return true;
  }
  if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") {
    return navigator.vibrate(200);
  }
  return false;
}

/** Через сколько мс вибрировать, или null, если фаза уже закончилась (истёкшая в фоне —
 * без «опоздавшего» сигнала, как и у звука, #269). */
export function vibrationDelayMs(endsAtMs: number, nowMs: number): number | null {
  const delay = endsAtMs - nowMs;
  return delay > 0 ? delay : null;
}
