import { useCallback, useEffect, useRef, useState } from "react";

import { fetchSessionsPage, type SessionResponseV2 } from "./apiV2";

export const JOURNAL_PAGE_SIZE = 25;

type State =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; items: SessionResponseV2[]; hasMore: boolean };

/**
 * Состояние Журнала v2 (R2): пагинация по существующему GET /sessions
 * (limit/offset). Живёт выше экрана деталей — возврат из деталей не
 * перезагружает список. Инварианты:
 *  - нет дублирующих запросов "Показать ещё" (inFlight ref);
 *  - слияние страниц по id (повторно пришедший id не дублируется);
 *  - сбой догрузки не стирает уже загруженные карточки (отдельная ошибка);
 *  - offset следующей страницы = число уже загруженных карточек, поэтому
 *    удаление карточки (removeById) не сдвигает выдачу.
 */
export function useJournalV2(initDataRaw: string) {
  const [state, setState] = useState<State>({ phase: "loading" });
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const itemsRef = useRef<SessionResponseV2[]>([]);

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading" });
    fetchSessionsPage(initDataRaw, JOURNAL_PAGE_SIZE, 0, "completed")
      .then((page) => {
        if (!cancelled) {
          itemsRef.current = page.sessions;
          setState({ phase: "ready", items: page.sessions, hasMore: page.has_more });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  const loadMore = useCallback(async () => {
    if (inFlight.current) {
      return;
    }
    inFlight.current = true;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await fetchSessionsPage(initDataRaw, JOURNAL_PAGE_SIZE, itemsRef.current.length, "completed");
      const known = new Set(itemsRef.current.map((item) => item.id));
      const merged = [...itemsRef.current, ...page.sessions.filter((item) => !known.has(item.id))];
      itemsRef.current = merged;
      setState({ phase: "ready", items: merged, hasMore: page.has_more });
    } catch (error) {
      setMoreError(error instanceof Error ? error.message : String(error));
    } finally {
      inFlight.current = false;
      setLoadingMore(false);
    }
  }, [initDataRaw]);

  const removeById = useCallback((sessionId: number) => {
    itemsRef.current = itemsRef.current.filter((item) => item.id !== sessionId);
    setState((current) =>
      current.phase === "ready" ? { ...current, items: itemsRef.current } : current);
  }, []);

  return { state, loadingMore, moreError, loadMore, removeById };
}
