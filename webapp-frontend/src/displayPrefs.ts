import { useSyncExternalStore } from "react";

import type { DisplayPreferences } from "./api";
import { isThemePref } from "./theme";

// Единицы и тема (#268): серверные настройки (/api/profile/prefs) кешируются в модульном сторе,
// чтобы любой экран мог показать вес/рост в выбранных единицах, а main.tsx — применить тему.
// localStorage — только кеш для первого кадра до ответа сервера (источник правды — сервер).

const STORAGE_KEY = "pullup.displayPrefs";

export const DEFAULT_PREFS: DisplayPreferences = { weight_unit: "kg", height_unit: "cm", theme: "auto" };

function load(): DisplayPreferences {
  try {
    const raw = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null") as Partial<DisplayPreferences> | null;
    if (raw) {
      return {
        weight_unit: raw.weight_unit === "lb" ? "lb" : "kg",
        height_unit: raw.height_unit === "in" ? "in" : "cm",
        theme: isThemePref(raw.theme) ? raw.theme : "auto",
      };
    }
  } catch {
    // нет localStorage / битый JSON — дефолты
  }
  return DEFAULT_PREFS;
}

let current: DisplayPreferences = load();
const listeners = new Set<() => void>();

export function getDisplayPrefs(): DisplayPreferences {
  return current;
}

export function setDisplayPrefs(next: DisplayPreferences): void {
  if (
    next.weight_unit === current.weight_unit &&
    next.height_unit === current.height_unit &&
    next.theme === current.theme
  ) {
    return;
  }
  current = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // не критично
  }
  listeners.forEach((listener) => listener());
}

export function subscribeDisplayPrefs(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useDisplayPrefs(): DisplayPreferences {
  return useSyncExternalStore(subscribeDisplayPrefs, getDisplayPrefs);
}
