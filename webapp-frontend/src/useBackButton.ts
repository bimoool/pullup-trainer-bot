import {
  mountBackButton,
  showBackButton,
  hideBackButton,
  onBackButtonClick,
  offBackButtonClick,
} from "@telegram-apps/sdk";
import { useEffect, useRef } from "react";

import { createBackButtonStack, type BackButtonAdapter } from "./backButtonStack";

/**
 * Hook для интеграции Telegram BackButton (issue #202, #249, переработан в #224).
 *
 * Управляет «назад» Telegram через общий стек (backButtonStack.ts):
 *  - кнопка видна, пока смонтирован хотя бы один экран с этим хуком (на корневых вкладках — скрыта);
 *  - клик получает ТОЛЬКО верхний (последний смонтированный) экран — никакой двойной навигации;
 *  - подписка на SDK одна на всё приложение, при пустом стеке снимается и кнопка прячется.
 *
 * Обработчик читается в момент клика из ref, поэтому всегда актуален; `deps` оставлен для
 * совместимости вызовов и больше не перезапускает подписку (иначе перерисованный родитель
 * «перепрыгивал» бы выше дочернего экрана в стеке).
 *
 * SDK v2: вне Telegram-клиента функции недоступны (isAvailable() == false) — graceful no-op
 * (тот же принцип, что у initData в App.tsx, issue #23/#28). mountBackButton() нужен до
 * show/hide (isAvailable() у show истинно только после mount, issue #249). unmount() не вызываем —
 * только при полном удалении Mini App.
 *
 * @param onClickHandler обработчик клика «назад»
 * @param _deps не используется (см. выше)
 * @param enabled false — экран временно не претендует на кнопку (например, корневой шаг мастера)
 */
const sdkAdapter: BackButtonAdapter = {
  available: () => Boolean(mountBackButton.isAvailable?.()),
  setVisible: (visible) => {
    try {
      mountBackButton();
      if (visible) {
        if (showBackButton.isAvailable?.()) {
          showBackButton();
        }
      } else if (hideBackButton.isAvailable?.()) {
        hideBackButton();
      }
    } catch (error) {
      console.error("BackButton toggle failed", error);
    }
  },
  subscribe: (listener) => {
    const remove = onBackButtonClick.isAvailable?.() ? onBackButtonClick(listener) : undefined;
    return () => {
      remove?.();
      if (offBackButtonClick.isAvailable?.()) {
        offBackButtonClick(listener);
      }
    };
  },
};

const stack = createBackButtonStack(sdkAdapter);

// Нижняя навигация скрыта на всех «pushed»-экранах (деталь, форма, поиск …) — как в эталоне; «назад»
// остаётся в шапке экрана и в Telegram BackButton. Счётчик, а не флаг: вложенные экраны не мешают друг другу.
let navHiddenCount = 0;
function setNavHidden(delta: number) {
  navHiddenCount = Math.max(0, navHiddenCount + delta);
  if (typeof document !== "undefined") {
    document.documentElement.classList.toggle("vp-nav-hidden", navHiddenCount > 0);
  }
}

/** @param hideNav false для оверлеев-шторок (ActionSheet, JournalEntrySheet): навигация под ними остаётся. */
export function useBackButton(onClickHandler: () => void, _deps: React.DependencyList = [], enabled = true, hideNav = true) {
  useEffect(() => {
    if (!enabled || !hideNav) {
      return;
    }
    setNavHidden(1);
    return () => setNavHidden(-1);
  }, [enabled, hideNav]);
  const handlerRef = useRef(onClickHandler);
  useEffect(() => {
    handlerRef.current = onClickHandler;
  });
  useEffect(() => {
    if (!enabled) {
      return;
    }
    return stack.push(() => handlerRef.current);
  }, [enabled]);
}
