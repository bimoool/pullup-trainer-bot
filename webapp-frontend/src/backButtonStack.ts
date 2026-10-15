// Стек обработчиков Telegram BackButton (#224). Раньше каждый экран с useBackButton сам звал
// show/onClick/hide: при вложенных экранах (родитель + дочерний) клик вызывал ОБА обработчика
// (двойная навигация), а размонтирование дочернего прятало кнопку, пока родитель ещё на экране.
// Теперь кнопка видна, пока в стеке есть хотя бы один экран, клик получает только верхний, а
// подписка на SDK одна. Чистая часть без SDK — проверяется tests/backButtonStack.test.ts.

export type BackButtonAdapter = {
  /** Есть ли вообще BackButton у клиента (вне Telegram — false, всё превращается в no-op). */
  available: () => boolean;
  setVisible: (visible: boolean) => void;
  /** Подписка на клик; возвращает отписку. */
  subscribe: (listener: () => void) => () => void;
};

type Entry = { handler: () => void };

export function createBackButtonStack(adapter: BackButtonAdapter, schedule: (task: () => void) => void = queueMicrotask) {
  const entries: Entry[] = [];
  // null — состояние кнопки у клиента неизвестно (старт приложения). Раньше стартовало с false: если клиент оставил
  // кнопку видимой (перезагрузка с вложенного экрана), стек считал её скрытой и не прятал — на Главной висела
  // «Назад» без обработчика (аудит staging 6475bc0). Первая синхронизация приводит кнопку к состоянию стека.
  let visible: boolean | null = null;
  let unsubscribe: (() => void) | null = null;
  let pending = false;

  function onClick() {
    entries[entries.length - 1]?.handler();
  }

  function sync() {
    pending = false;
    const wanted = entries.length > 0;
    if (wanted && unsubscribe === null && adapter.available()) {
      unsubscribe = adapter.subscribe(onClick);
    }
    if (!wanted && unsubscribe !== null) {
      unsubscribe();
      unsubscribe = null;
    }
    // Показать или привести неизвестное состояние — только при доступном SDK; спрятать показанную нами — всегда.
    const canApply = wanted || visible === null ? adapter.available() : true;
    if (wanted !== visible && canApply) {
      visible = wanted;
      adapter.setVisible(wanted);
    }
  }

  // Смена экрана = размонтирование старого и монтирование нового в одном коммите React: схлопываем
  // в одну синхронизацию, чтобы кнопка не мигала hide→show.
  function requestSync() {
    if (!pending) {
      pending = true;
      schedule(sync);
    }
  }

  return {
    /** Регистрирует экран; handler читается в момент клика (get), поэтому всегда свежий. */
    push(get: () => () => void): () => void {
      const entry: Entry = { handler: () => get()() };
      entries.push(entry);
      requestSync();
      return () => {
        const index = entries.indexOf(entry);
        if (index !== -1) {
          entries.splice(index, 1);
        }
        requestSync();
      };
    },
    size: () => entries.length,
    isVisible: () => visible === true,
    /** Запросить синхронизацию без смены стека — при старте приложения, когда состояние клиента неизвестно. */
    reconcile: requestSync,
    /** Синхронно применить отложенное (для тестов). */
    flush: sync,
  };
}
