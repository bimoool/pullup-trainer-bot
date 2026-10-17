/**
 * Решение владельца 2026-10-17: Premium-функции (факультатив, доп./свои тренировки, другие программы, свой контент,
 * добавление в план) остаются видимыми; без подписки сервер отвечает 402 `{"detail": {"code": "subscription_required"}}`.
 * Любой такой ответ (api.ts / apiV2.ts → extractErrorMessage) поднимает здесь одно событие, App показывает поверх
 * текущего экрана объяснение и путь к подписке. Экран под ним не размонтируется — введённое в форму не теряется.
 * Истина — всегда сервер; это только транспорт события.
 */
export const SUBSCRIPTION_REQUIRED_CODE = "subscription_required";

const EVENT_NAME = "pullup:subscription-required";

/** openScreen — сразу экран подписки (кнопка «Открыть подписку» в заранее показанном объяснении), без листа. */
export type SubscriptionRequiredDetail = { message: string | null; openScreen?: boolean };

export function notifySubscriptionRequired(message: string | null): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent<SubscriptionRequiredDetail>(EVENT_NAME, { detail: { message } }));
}

/** Экран подписки поверх текущего (текущий экран и введённое в нём сохраняются). */
export function openSubscriptionScreen(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent<SubscriptionRequiredDetail>(EVENT_NAME, { detail: { message: null, openScreen: true } }));
}

export function subscribeSubscriptionRequired(listener: (detail: SubscriptionRequiredDetail) => void): () => void {
  const handler = (event: Event) => listener((event as CustomEvent<SubscriptionRequiredDetail>).detail);
  window.addEventListener(EVENT_NAME, handler);
  return () => window.removeEventListener(EVENT_NAME, handler);
}

/** 402 с кодом subscription_required → событие. Читает клон: тело ответа ещё нужно вызывающему для message. */
export async function reportIfSubscriptionRequired(response: Response): Promise<void> {
  if (response.status !== 402) {
    return;
  }
  try {
    const detail = (await response.clone().json())?.detail;
    if (detail?.code === SUBSCRIPTION_REQUIRED_CODE) {
      notifySubscriptionRequired(typeof detail.message === "string" ? detail.message : null);
    }
  } catch {
    // не JSON — не наш контракт
  }
}
