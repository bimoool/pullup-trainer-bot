// Шина событий @telegram-apps/sdk (#287 MED 4). На нативных iOS/Android клиентах init() SDK заменяет
// window.Telegram.WebView.receiveEvent своим: события клиента (theme_changed, safe_area_changed,
// content_safe_area_changed, fullscreen_changed) приходят ТОЛЬКО сюда, а WebApp.onEvent из
// telegram-web-app.js молчит. Подписка — тонкая обёртка над on(); полезная нагрузка — сырая, как её
// прислал клиент (snake_case). Сбой подписки не роняет приложение.
import { on } from "@telegram-apps/sdk";

export type SdkEventSubscribe = (event: string, handler: (payload: unknown) => void) => () => void;

export const subscribeSdkEvent: SdkEventSubscribe = (event, handler) => {
  try {
    const subscribe = on as unknown as (name: string, listener: (payload: unknown) => void) => () => void;
    return subscribe(event, handler);
  } catch (error) {
    console.error(`Telegram SDK event subscription failed: ${event}`, error);
    return () => {};
  }
};
