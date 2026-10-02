// Единая точка запуска платформенной части Telegram (#224): ready/expand/запрет свайпа/отступы +
// цвета хрома. Вызывается один раз из main.tsx после init() SDK.
import { subscribeDisplayPrefs } from "./displayPrefs";
import { applyTelegramChrome } from "./telegramChrome";
import { initTelegramPlatform } from "./telegramPlatform";

export function bootTelegram(): void {
  initTelegramPlatform();
  applyTelegramChrome();
  // Смена настройки темы Mini App («Как в Telegram»/«Светлая»/«Тёмная») меняет наши поверхности —
  // шапка/фон/нижняя панель Telegram должны следовать. Подписка регистрируется ПОСЛЕ подписки
  // main.tsx (она применяет палитру), поэтому читает уже обновлённые токены.
  subscribeDisplayPrefs(applyTelegramChrome);
}
