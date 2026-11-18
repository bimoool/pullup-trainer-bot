import { useEffect, useState } from "react";
import { fetchTimerPreferences } from "./api";

/** Server preference belongs to this account/mount. Pending or failed reads never borrow another timer's volume. */
export function usePhaseSoundVolume(initDataRaw: string): number | null {
  const [saved, setSaved] = useState<{ account: string; volume: number } | null>(null);
  useEffect(() => {
    let cancelled = false;
    void fetchTimerPreferences(initDataRaw).then((prefs) => {
      if (!cancelled) {
        setSaved({ account: initDataRaw, volume: prefs.sound_volume_percent });
      }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [initDataRaw]);
  return saved?.account === initDataRaw ? saved.volume : null;
}
