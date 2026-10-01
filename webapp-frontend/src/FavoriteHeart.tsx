import { useEffect, useRef, useState } from "react";

import { listFavorites, setFavorite, type FavoriteTargetType } from "./apiV2";
import { isFavorite, markFavoritesSeen } from "./favorites";

type Props = {
  initDataRaw: string;
  targetType: FavoriteTargetType;
  targetId: number;
};

/**
 * Сердечко «В избранное» (issue #272): мгновенный оптимистичный тумблер, при
 * ошибке запроса состояние откатывается и показывается короткое сообщение.
 */
export function FavoriteHeart({ initDataRaw, targetType, targetId }: Props) {
  const [favorite, setFavoriteState] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);

  useEffect(() => {
    let cancelled = false;
    listFavorites(initDataRaw)
      .then((list) => !cancelled && setFavoriteState(isFavorite(list, targetType, targetId)))
      .catch(() => undefined)
      .finally(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, targetType, targetId]);

  async function toggle() {
    if (pending.current) {
      return;
    }
    const next = !favorite;
    pending.current = true;
    setError(null);
    setFavoriteState(next);
    try {
      await setFavorite(initDataRaw, targetType, targetId, next);
      if (next) {
        markFavoritesSeen();
      }
    } catch {
      setFavoriteState(!next);
      setError("Не удалось обновить избранное");
    } finally {
      pending.current = false;
    }
  }

  return (
    <>
      <button
        type="button"
        className={favorite ? "favorite-heart favorite-heart-on" : "favorite-heart"}
        data-testid="favorite-heart"
        aria-pressed={favorite}
        aria-label={favorite ? "Убрать из избранного" : "В избранное"}
        disabled={!loaded}
        onClick={() => void toggle()}
      >
        {favorite ? "♥" : "♡"}
      </button>
      {error && <p className="hint favorite-error" data-testid="favorite-error" role="alert">{error}</p>}
    </>
  );
}
