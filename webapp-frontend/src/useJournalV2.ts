import { useCallback, useEffect, useRef, useState } from "react";

import { fetchJournalDays, fetchSessionsPage, type JournalDaysResponse, type SessionResponseV2 } from "./apiV2";
import { currentMonthIn, DEFAULT_JOURNAL_TZ, monthRange, shiftMonth } from "./journalCalendarModel";
import { mergeMorePage } from "./journalPaging";

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
 *  - устаревший ответ (быстрое переключение месяца) отбрасывается; то же для «Показать ещё»
 *    (эпоха списка, journalPaging.mergeMorePage).
 *
 * Стартовый месяц: текущий в поясе пользователя; если он пуст, а тренировки
 * есть — месяц самой свежей (иначе новичок с вчерашней тренировкой 1-го числа
 * увидел бы пустой экран).
 */
export function useJournalV2(initDataRaw: string, restore?: { month: string; day: string | null } | null) {
  // restore — возврат из «Открыть тренировку»: тот же месяц/день, без выбора стартового месяца.
  const restoreRef = useRef(restore ?? null);
  const [month, setMonthState] = useState<string | null>(null);
  const [day, setDay] = useState<string | null>(restoreRef.current?.day ?? null);
  const [daysInfo, setDaysInfo] = useState<JournalDaysResponse | null>(null);
  const [state, setState] = useState<State>({ phase: "loading" });
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);
  // Перезагрузка списка после записи (#263): новая запись должна появиться без перехода по месяцам.
  const [reloadKey, setReloadKey] = useState(0);
  const inFlight = useRef(false);
  // Эпоха списка: растёт при каждой перезагрузке (месяц/день/reload); ответ «Показать ещё» старой эпохи отбрасывается.
  const listEpoch = useRef(0);
  const itemsRef = useRef<SessionResponseV2[]>([]);
  const daysCache = useRef(new Map<string, JournalDaysResponse>());

  // 1) Определяем стартовый месяц (пояс пользователя приходит с /journal/days).
  useEffect(() => {
    let cancelled = false;
    daysCache.current.clear();
    async function bootstrap() {
      try {
        const restored = restoreRef.current;
        if (restored !== null) {
          const info = await fetchJournalDays(initDataRaw, restored.month);
          if (!cancelled) {
            daysCache.current.set(info.month, info);
            setDaysInfo(info);
            setMonthState(restored.month);
          }
          return;
        }
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
    listEpoch.current += 1;
    inFlight.current = false;
    setLoadingMore(false);
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
  }, [initDataRaw, month, day, reloadKey]);

  const loadMore = useCallback(async () => {
    if (inFlight.current || month === null) {
      return;
    }
    inFlight.current = true;
    setLoadingMore(true);
    setMoreError(null);
    const startedEpoch = listEpoch.current;
    const range = day !== null ? { from: day, to: day } : monthRange(month);
    try {
      const page = await fetchSessionsPage(initDataRaw, JOURNAL_PAGE_SIZE, itemsRef.current.length, "completed", range);
      const merged = mergeMorePage(itemsRef.current, page.sessions, startedEpoch, listEpoch.current);
      if (merged === null) {
        return; // список уже перезагружен для другого диапазона — старая страница не нужна
      }
      itemsRef.current = merged;
      setState({ phase: "ready", items: merged, hasMore: page.has_more });
    } catch (error) {
      if (startedEpoch === listEpoch.current) {
        setMoreError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      if (startedEpoch === listEpoch.current) {
        inFlight.current = false;
        setLoadingMore(false);
      }
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

  /** Записали новую сессию: перегрузить список и точки календаря (месяц записи). */
  const reloadAfterLog = useCallback((date: string) => {
    daysCache.current.clear();
    setDay(null);
    const logMonth = date.slice(0, 7);
    if (logMonth !== month) {
      setMonthState(logMonth);
    } else {
      setReloadKey((value) => value + 1);
      refreshDays();
    }
  }, [month, refreshDays]);

  const removeById =useCallback((sessionId: number) => {
    itemsRef.current = itemsRef.current.filter((item) => item.id !== sessionId);
    setState((current) =>
      current.phase === "ready" ? { ...current, items: itemsRef.current } : current);
    refreshDays();
  }, [refreshDays]);

  /** После правки/клона (#262): заново загрузить список и точки календаря;
   * jumpToMonth ("YYYY-MM") — перейти к месяцу новой записи. */
  const reload = useCallback((jumpToMonth?: string) => {
    refreshDays();
    if (jumpToMonth !== undefined && jumpToMonth !== month) {
      setDay(null);
      setMonthState(jumpToMonth);
    } else {
      setReloadKey((key) => key + 1);
    }
  }, [refreshDays, month]);

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
    state, loadingMore, moreError, loadMore, removeById, refreshDays, reloadAfterLog, reload,
    month, day, shift, toggleDay,
    timezone: daysInfo?.timezone ?? DEFAULT_JOURNAL_TZ,
    dayCounts: new Map((daysInfo?.month === month ? daysInfo.days : []).map((entry) => [entry.date, entry.count])),
  };
}
