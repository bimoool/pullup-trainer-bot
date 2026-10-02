import { useEffect, useState } from "react";

import { fetchProfile } from "./api";
import { todayInTimeZone } from "./todayInTimeZone";

// Пояс профиля берётся один раз на initData (кэш на модуль) и обновляется после сохранения профиля.
const cache = new Map<string, Promise<string | null>>();

export function loadProfileTimeZone(initDataRaw: string): Promise<string | null> {
  let pending = cache.get(initDataRaw);
  if (pending === undefined) {
    pending = fetchProfile(initDataRaw)
      .then((profile) => profile.timezone ?? null)
      .catch(() => {
        cache.delete(initDataRaw);
        return null;
      });
    cache.set(initDataRaw, pending);
  }
  return pending;
}

/** Сбросить кэш (смена часового пояса в профиле). */
export function invalidateProfileTimeZone(): void {
  cache.clear();
}

/** Пояс профиля (undefined, пока грузится/неизвестен) и «сегодня» в нём (до загрузки — день устройства). */
export function useProfileToday(initDataRaw: string): { timeZone: string | undefined; today: string } {
  const [timeZone, setTimeZone] = useState<string | undefined>(undefined);
  useEffect(() => {
    let cancelled = false;
    void loadProfileTimeZone(initDataRaw).then((zone) => {
      if (!cancelled && zone !== null) {
        setTimeZone(zone);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);
  return { timeZone, today: todayInTimeZone(timeZone) };
}
