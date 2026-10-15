import type { Page } from "@playwright/test";

/**
 * Управляемая запись IndexedDB (без фиксированных пауз): тест сам решает, когда запись очереди Live «долетает».
 *  - "pass" — как обычно;
 *  - "hold" — put откладывается: исходная транзакция завершается пустой, её oncomplete не вызывается, пока тест не
 *    позовёт releaseIdbWrites() (тогда данные пишутся новой транзакцией и вызывается исходный oncomplete). Страница,
 *    закрытая до release, ничего не записала — как настоящий сбой «закрыли до коммита»;
 *  - "fail" — put бросает QuotaExceededError (запись не удалась).
 * Перехват — на уровне IDBObjectStore.put / IDBTransaction.on*, т. е. ровно того, что делает idb-keyval `set`.
 * Скрипт ставится до загрузки страницы; новая страница/перезагрузка стартует в режиме "pass".
 */
export async function installIdbWriteGate(page: Page): Promise<void> {
  await page.addInitScript(() => {
    type Handler = ((event: Event) => void) | null;
    type Held = {
      tx: IDBTransaction; store: string; puts: [unknown, IDBValidKey | undefined][];
      oncomplete: Handler; onerror: Handler; onabort: Handler;
    };
    const gate = { mode: "pass" as "pass" | "hold" | "fail", held: [] as Held[] };
    const heldByTx = new WeakMap<IDBTransaction, Held>();
    (window as unknown as { __idbGate: typeof gate }).__idbGate = gate;

    const originalPut = IDBObjectStore.prototype.put;
    IDBObjectStore.prototype.put = function put(this: IDBObjectStore, value: unknown, key?: IDBValidKey) {
      if (gate.mode === "fail") {
        throw new DOMException("e2e: запись IndexedDB не удалась", "QuotaExceededError");
      }
      if (gate.mode === "pass") {
        return originalPut.call(this, value, key);
      }
      let held = heldByTx.get(this.transaction);
      if (held === undefined) {
        held = { tx: this.transaction, store: this.name, puts: [], oncomplete: null, onerror: null, onabort: null };
        heldByTx.set(this.transaction, held);
        gate.held.push(held);
      }
      held.puts.push([value, key]);
      return {} as IDBRequest<IDBValidKey>;
    };
    for (const name of ["oncomplete", "onerror", "onabort"] as const) {
      const native = Object.getOwnPropertyDescriptor(IDBTransaction.prototype, name)!;
      Object.defineProperty(IDBTransaction.prototype, name, {
        configurable: true,
        get(this: IDBTransaction) {
          return native.get!.call(this);
        },
        set(this: IDBTransaction, handler: Handler) {
          const held = heldByTx.get(this);
          if (held !== undefined) {
            held[name] = handler;  // гейт отвечает сам — после release
            return;
          }
          native.set!.call(this, handler);
        },
      });
    }

    (window as unknown as { __releaseIdbWrites: () => number }).__releaseIdbWrites = () => {
      const batch = gate.held.splice(0);
      for (const held of batch) {
        const tx = held.tx.db.transaction(held.store, "readwrite");
        const store = tx.objectStore(held.store);
        for (const [value, key] of held.puts) {
          originalPut.call(store, value, key);
        }
        tx.addEventListener("complete", (event) => held.oncomplete?.(event));
        tx.addEventListener("error", (event) => held.onerror?.(event));
      }
      return batch.length;
    };
  });
}

export async function setIdbWriteMode(page: Page, mode: "pass" | "hold" | "fail"): Promise<void> {
  await page.evaluate((next) => {
    (window as unknown as { __idbGate: { mode: string } }).__idbGate.mode = next;
  }, mode);
}

export async function heldIdbWrites(page: Page): Promise<number> {
  return page.evaluate(() => (window as unknown as { __idbGate: { held: unknown[] } }).__idbGate.held.length);
}

/** Отпустить отложенные записи (их данные пишутся, исходные oncomplete вызываются) и вернуть режим "pass". */
export async function releaseIdbWrites(page: Page): Promise<number> {
  return page.evaluate(() => {
    const w = window as unknown as { __idbGate: { mode: string }; __releaseIdbWrites: () => number };
    w.__idbGate.mode = "pass";
    return w.__releaseIdbWrites();
  });
}
