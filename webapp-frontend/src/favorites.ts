import type { FavoriteTargetType, FavoriteV2 } from "./apiV2";

/** Флаг «пользователь уже пользовался Избранным» — по нему Главная решает,
 * показывать ли подсказку у пустого ряда (issue #272). */
export const FAVORITES_SEEN_KEY = "favorites_seen";

export function isFavorite(favorites: FavoriteV2[], targetType: FavoriteTargetType, targetId: number): boolean {
  return favorites.some((f) => f.target_type === targetType && f.target_id === targetId);
}

/** Подсказку «Нажмите ♡…» видит только тот, кто ни разу ничего не добавлял; ряд с
 * избранным — когда есть что показать; иначе (был, но опустел) ряд скрыт. */
export function favoritesRowMode(count: number, everFavorited: boolean): "items" | "hint" | "hidden" {
  if (count > 0) {
    return "items";
  }
  return everFavorited ? "hidden" : "hint";
}

export function readFavoritesSeen(): boolean {
  try {
    return window.localStorage.getItem(FAVORITES_SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

export function markFavoritesSeen(): void {
  try {
    window.localStorage.setItem(FAVORITES_SEEN_KEY, "1");
  } catch {
    // localStorage недоступен — подсказка просто покажется снова
  }
}
