import { useCallback, useEffect, useRef, useState } from "react";

import { fetchJournalDays, fetchSessionsPage, type JournalDaysResponse, type SessionResponseV2 } from "./apiV2";
import { currentMonthIn, DEFAULT_JOURNAL_TZ, monthRange, shiftMonth } from "./journalCalendar";

export const JOURNAL_PAGE_SIZE = 25;

type State =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; items: SessionResponseV2[]; hasMore: boolean };

/**
 * Состояние Журнала v2 (R2 + #256): сессии грузятся ПО МЕСЯЦУ (или по выбранному
 * дню) через GET /sessions?date_from&date_to, точки календаря — из GET
 * /journal/days; клиент никогда не сканирует всю историю. Живёт выше экрана
 * деталей — возврат из деталей не перезагружает список. Инварианты:
 *  - нет дублирующих запросов "Показать ещё" (inFlight ref);
 *  - слияние страниц по id (повторно пришедший id не дублируется);
 *  - сбой догрузки не стирает уже загруженные карточки (отдельная ошибка);
 *  - offset следующей страницы = число уже загруженных карточек, поэтому
 *    удаление карточки (removeById) не сдвигает выдачу;
 *  - устаревший ответ (быстрое переключение месяца) отбрасывается.
 *
 * Стартовый месяц: текущий в поясе пользователя; если он пуст, а тренировки
 * есть — месяц самой свежей (иначе новичок с вчерашней тренировкой 1-го числа
 * увидел бы пустой экран).
 */
export function useJournalV2(initDataRaw: string) {
  const [month, setMonthState] = useState<string | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const [daysInfo, setDaysInfo] = useState<JournalDaysResponse | null>(null);
  const [state, setState] = useState<State>({ phase: "loading" });
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const itemsRef = useRef<SessionResponseV2[]>([]);
  const daysCache = useRef(new Map<string, JournalDaysResponse>());

  // 1) Определяем стартовый месяц (пояс пользователя приходит с /journal/days).
  useEffect(() => {
    let cancelled = false;
    daysCache.current.clear();
    async function bootstrap() {
      try {
        const guess = currentMonthIn(DEFAULT_JOURNAL_TZ);
        let info = await fetchJournalDays(initDataRaw, guess);
        const actual = currentMonthIn(info.timezone);
        if (actual !== info.month) {
          info = await fetchJournalDays(initDataRaw, actual);
        }
        if (info.days.length === 0 && info.latest_month !== null && info.latest_month !== info.month) {
          info = await fetchJournalDays(initDataRaw, info.latest_month);
        }
        if (!cancelled) {
          daysCache.current.set(info.month, info);
          setDaysInfo(info);
          setMonthState(info.month);
        }
      } catch (error) {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  // 2) Точки календаря выбранного месяца.
  useEffect(() => {
    if (month === null) {
      return;
    }
    const cached = daysCache.current.get(month);
    if (cached !== undefined) {
      setDaysInfo(cached);
      return;
    }
    let cancelled = false;
    fetchJournalDays(initDataRaw, month)
      .then((info) => {
        if (!cancelled) {
          daysCache.current.set(month, info);
          setDaysInfo(info);
        }
      })
      .catch(() => {
        // календарь — украшение: без точек список всё равно работает
        if (!cancelled) {
          setDaysInfo((current) => (current === null ? null : { ...current, month, days: [] }));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, month]);

  // 3) Список за месяц или за выбранный день.
  useEffect(() => {
    if (month === null) {
      return;
    }
    let cancelled = false;
    const range = day !== null ? { from: day, to: day } : monthRange(month);
    setState({ phase: "loading" });
    setMoreError(null);
    fetchSessionsPage(initDataRaw, JOURNAL_PAGE_SIZE, 0, "completed", range)
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
  }, [initDataRaw, month, day]);

  const loadMore = useCallback(async () => {
    if (inFlight.current || month === null) {
      return;
    }
    inFlight.current = true;
    setLoadingMore(true);
    setMoreError(null);
    const range = day !== null ? { from: day, to: day } : monthRange(month);
    try {
      const page = await fetchSessionsPage(initDataRaw, JOURNAL_PAGE_SIZE, itemsRef.current.length, "completed", range);
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
  }, [initDataRaw, month, day]);

  /** Точка дня могла опираться на удалённую тренировку — пересчитать месяц. */
  const refreshDays = useCallback(() => {
    daysCache.current.clear();
    if (month === null) {
      return;
    }
    fetchJournalDays(initDataRaw, month)
      .then((info) => {
        daysCache.current.set(month, info);
        setDaysInfo(info);
      })
      .catch(() => undefined);
  }, [initDataRaw, month]);

  const removeById = useCallback((sessionId: number) => {
    itemsRef.current = itemsRef.current.filter((item) => item.id !== sessionId);
    setState((current) =>
      current.phase === "ready" ? { ...current, items: itemsRef.current } : current);
    refreshDays();
  }, [refreshDays]);

  const setMonth = useCallback((next: string) => {
    setDay(null);
    setMonthState(next);
  }, []);
  const shift = useCallback((delta: number) => {
    if (month !== null) {
      setMonth(shiftMonth(month, delta));
    }
  }, [month, setMonth]);
  /** Тап по дню выбирает его, повторный тап снимает выбор. */
  const toggleDay = useCallback((date: string) => {
    setDay((current) => (current === date ? null : date));
  }, []);

  return {
    state, loadingMore, moreError, loadMore, removeById, refreshDays,
    month, day, shift, toggleDay,
    timezone: daysInfo?.timezone ?? DEFAULT_JOURNAL_TZ,
    dayCounts: new Map((daysInfo?.month === month ? daysInfo.days : []).map((entry) => [entry.date, entry.count])),
  };
}
