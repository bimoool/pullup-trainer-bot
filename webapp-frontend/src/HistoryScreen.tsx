import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { deleteHistoryWorkout, fetchHistory, type HistoryEntry } from "./api";
import { HistoryEditForm } from "./HistoryEditForm";
import { JournalCalendar } from "./JournalCalendar";
import { localDateKey, monthRange } from "./journalCalendarModel";
import { JournalSessionCard, JournalV2Detail, JournalV2Footer } from "./JournalV2";
import { JournalTimeline } from "./JournalTimeline";
import { BackdatedWorkoutForm, FreeActivityForm, LogActivitySheet, type LogKind } from "./LogActivitySheet";
import { useJournalV2 } from "./useJournalV2";

type Props = {
  initDataRaw: string;
  /** Меняется, когда Главная просит открыть шторку «Записать» (#263). */
  logRequest?: number;
  /** С какой тренировкой открыть форму записи (Workout Detail «Записать»). */
  logWorkoutId?: number | null;
  /** «← Назад» из формы, открытой с Workout Detail: вернуться на деталь (#277, D1). */
  onLogBack?: () => void;
  /** «Открыть тренировку» из записи Журнала (#281) — Workout Detail на вкладке «Главная». */
  onOpenWorkout?: (workoutId: number, restore: JournalRestore) => void;
  /** Вернуться на тот же месяц/день и открыть ту же запись (Back из «Открыть тренировку»). */
  restore?: JournalRestore | null;
};

/** Где пользователь был в Журнале: месяц, выбранный день и открытая запись. */
export type JournalRestore = { month: string; day: string | null; sessionId: number | null };

const PAGE_SIZE = 20;

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; items: HistoryEntry[]; hasMore: boolean; loadingMore: boolean };

/** "2026-09-03" -> "03.09.2026" — тот же формат, что format_history_entry
 * бота (app/bot/handlers/history.py), без сдвига дня по локальному
 * часовому поясу браузера (день уже фиксирован сервером). */
function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  return `${day}.${month}.${year}`;
}

export function HistoryScreen({ initDataRaw, logRequest = 0, logWorkoutId = null, onLogBack, onOpenWorkout, restore = null }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  // «+ Записать» (#263): шторка выбора и затем одна из двух форм.
  const [logSheetOpen, setLogSheetOpen] = useState(logRequest > 0 && logWorkoutId === null);
  // Записать с Workout Detail — сразу форма «Тренировка из моих» с выбранной тренировкой.
  const [logForm, setLogForm] = useState<LogKind | null>(logWorkoutId !== null ? "workout" : null);
  // Форма открыта с Workout Detail (только пока не сохранили): «← Назад» ведёт обратно на деталь.
  const [logFromDetail, setLogFromDetail] = useState(logWorkoutId !== null);
  const [editingWorkoutId, setEditingWorkoutId] = useState<number | null>(null);
  const [deletingWorkoutId, setDeletingWorkoutId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // Журнал v2 (R2): завершённые TrainingSession поверх legacy Workout ниже —
  // модели остаются разными и НЕ сливаются в одну хронологию. Состояние
  // (загруженные страницы) живёт здесь, выше экрана деталей: возврат из
  // деталей сохраняет уже загруженный Журнал. Сбой этой секции не роняет
  // legacy-историю ниже.
  const journal = useJournalV2(initDataRaw, restore);
  const [detailSessionId, setDetailSessionId] = useState<number | null>(restore?.sessionId ?? null);
  const [calendarExpanded, setCalendarExpanded] = useState(false);

  // Legacy-история грузится за тот же месяц/день, что и v2 (#256): диапазон
  // уходит на бэкенд, клиент не фильтрует полную историю.
  const range = journal.month === null ? null : journal.day !== null
    ? { from: journal.day, to: journal.day }
    : monthRange(journal.month);
  const rangeKey = range === null ? null : `${range.from}..${range.to}`;

  useEffect(() => {
    if (range === null) {
      return;
    }
    let cancelled = false;
    setState({ phase: "loading" });
    async function load() {
      try {
        const page = await fetchHistory(initDataRaw, 0, PAGE_SIZE, range ?? undefined);
        if (!cancelled) {
          setState({ phase: "ready", items: page.items, hasMore: page.has_more, loadingMore: false });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
    // range пересоздаётся каждый рендер — зависим от его строкового ключа
  }, [initDataRaw, rangeKey]);

  async function reloadFirstPage() {
    try {
      const page = await fetchHistory(initDataRaw, 0, PAGE_SIZE, range ?? undefined);
      setState({ phase: "ready", items: page.items, hasMore: page.has_more, loadingMore: false });
    } catch (error) {
      setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  async function loadMore() {
    if (state.phase !== "ready") {
      return;
    }
    setState({ ...state, loadingMore: true });
    try {
      const page = await fetchHistory(initDataRaw, state.items.length, PAGE_SIZE, range ?? undefined);
      setState({
        phase: "ready",
        items: [...state.items, ...page.items],
        hasMore: page.has_more,
        loadingMore: false,
      });
    } catch (error) {
      setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  async function handleDelete(workoutId: number, isBackdated: boolean) {
    // Каскадные (обычные) тренировки удаляются с пересчётом цепочки целей
    // (issue #146, решение Кирилла — вариант A) — последствия серьёзнее,
    // чем для бэкдейта/свободных (там пересчитывать нечего), формулировка
    // предупреждает об этом явно, не только "нельзя отменить".
    const message = isBackdated
      ? "Удалить эту тренировку из истории? Отменить это будет нельзя."
      : "Удалить эту тренировку? Это пересчитает цели всех следующих тренировок. Отменить это будет нельзя.";
    if (!window.confirm(message)) {
      return;
    }
    setDeleteError(null);
    setDeletingWorkoutId(workoutId);
    try {
      await deleteHistoryWorkout(initDataRaw, workoutId);
      await reloadFirstPage();
      journal.refreshDays();
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : String(error));
    } finally {
      setDeletingWorkoutId(null);
    }
  }

  if (logForm !== null) {
    const FormComponent = logForm === "workout" ? BackdatedWorkoutForm : FreeActivityForm;
    return (
      <FormComponent
        {...(logForm === "workout" && logWorkoutId !== null && logFromDetail ? { initialWorkoutId: logWorkoutId } : {})}
        initDataRaw={initDataRaw}
        onBack={() => {
          if (logFromDetail && onLogBack !== undefined) {
            onLogBack();
            return;
          }
          setLogForm(null);
        }}
        onSaved={(date) => {
          setLogFromDetail(false);
          setLogForm(null);
          journal.reloadAfterLog(date);
        }}
      />
    );
  }

  if (editingWorkoutId !== null) {
    return (
      <HistoryEditForm
        initDataRaw={initDataRaw}
        workoutId={editingWorkoutId}
        onCancel={() => setEditingWorkoutId(null)}
        onDone={() => {
          setEditingWorkoutId(null);
          void reloadFirstPage();
        }}
      />
    );
  }

  const detailSession = detailSessionId !== null
    ? journal.state.phase === "ready" ? journal.state.items.find((item) => item.id === detailSessionId) ?? null : null
    : null;
  if (detailSession !== null) {
    return (
      <JournalV2Detail
        initDataRaw={initDataRaw}
        session={detailSession}
        timeZone={journal.timezone}
        onBack={() => setDetailSessionId(null)}
        onOpenWorkout={onOpenWorkout && journal.month !== null
          ? (workoutId) => onOpenWorkout(workoutId, { month: journal.month as string, day: journal.day, sessionId: detailSession.id })
          : undefined}
        onDeleted={(sessionId) => {
          journal.removeById(sessionId);
          setDetailSessionId(null);
        }}
        onEdited={() => {
          setDetailSessionId(null);
          journal.reload();
        }}
        onCloned={(date) => {
          setDetailSessionId(null);
          journal.reload(date.slice(0, 7));
        }}
      />
    );
  }

  function legacyCard(entry: HistoryEntry) {
    return (
      <div className="history-card" data-kind="legacy" key={`legacy-${entry.workout_id}`}>
        <p className="history-date">
          {formatDate(entry.performed_at)}
          {entry.is_backdated && <span className="hint"> (задним числом)</span>}
        </p>
        <p>
          Объём ({entry.equipment_a.label}): {entry.result_a}
          {entry.target_a !== null && `, следующая цель ${entry.target_a}`}
        </p>
        <p>
          Сила ({entry.equipment_b.label}): {entry.result_b}
          {entry.target_b !== null && `, следующая цель ${entry.target_b}`}
        </p>
        {entry.comment && <p className="hint">Комментарий: {entry.comment}</p>}
        <div className="history-card-actions">
          {/* Внесённые не в цепочку (бэкдейт/свободные, is_backdated) тоже
              редактируются (issue #106) — просто без пересчёта цели/каскада
              на бэкенде (WorkoutRepository.edit_noncascade_workout), кнопка
              одна для всех записей. */}
          <Button mode="outline" size="s" onClick={() => setEditingWorkoutId(entry.workout_id)}>
            ✏️ Изменить
          </Button>
          {/* Удаление (issue #146) — теперь и для каскадных тренировок
              (решение Кирилла, вариант A: удаление пересчитывает цепочку
              целей), не только бэкдейт/свободных — is_deletable
              (HistoryEntry в api.ts) сейчас всегда true. */}
          {entry.is_deletable && (
            <Button
              mode="outline"
              size="s"
              loading={deletingWorkoutId === entry.workout_id}
              onClick={() => void handleDelete(entry.workout_id, entry.is_backdated)}
            >
              🗑 Удалить
            </Button>
          )}
        </div>
      </div>
    );
  }

  const v2Items = journal.state.phase === "ready" ? journal.state.items : [];
  const legacyItems = state.phase === "ready" ? state.items : [];
  const loading = journal.month === null ? journal.state.phase !== "error" : journal.state.phase === "loading" || state.phase === "loading";
  const timelineEntries = [
    ...v2Items.map((session) => ({
      date: localDateKey(session.performed_at, journal.timezone),
      node: <JournalSessionCard key={`v2-${session.id}`} session={session} onOpen={setDetailSessionId} />,
    })),
    ...legacyItems.map((entry) => ({ date: entry.performed_at, node: legacyCard(entry) })),
  ];

  return (
    <div>
      {/* Заголовок переименован в "Журнал" вслед за вкладкой нижнего меню
          (issue #183, волна 5b) — само содержимое экрана не менялось. */}
      <div className="journal-title-row">
        <p className="plan-title">Журнал</p>
        <button type="button" className="journal-log-button" data-testid="journal-log-button" onClick={() => setLogSheetOpen(true)}>
          + Записать
        </button>
      </div>
      {logSheetOpen && (
        <LogActivitySheet
          onClose={() => setLogSheetOpen(false)}
          onPick={(kind) => { setLogSheetOpen(false); setLogForm(kind); }}
        />
      )}
      {journal.month !== null && (
        <JournalCalendar
          month={journal.month}
          dayCounts={journal.dayCounts}
          selectedDay={journal.day}
          today={localDateKey(new Date().toISOString(), journal.timezone)}
          expanded={calendarExpanded}
          onToggleExpanded={() => setCalendarExpanded((value) => !value)}
          onShift={journal.shift}
          onToggleDay={journal.toggleDay}
        />
      )}
      {deleteError && <p className="screen-message">Не удалось удалить тренировку: {deleteError}</p>}

      {journal.state.phase === "error" && (
        <p className="screen-message">Не удалось загрузить новые тренировки: {journal.state.message}</p>
      )}
      {state.phase === "error" && (
        <p className="screen-message">Не удалось загрузить историю: {state.message}</p>
      )}
      {loading && <p className="screen-message">Загружаю историю…</p>}
      {!loading && journal.month !== null && timelineEntries.length === 0
        && journal.state.phase !== "error" && state.phase !== "error" && (
        <p className="screen-message">
          {journal.day !== null ? "В этот день тренировок нет" : "В этом месяце тренировок нет"}
        </p>
      )}
      {!loading && timelineEntries.length > 0 && <JournalTimeline entries={timelineEntries} />}
      {!loading && (
        <JournalV2Footer
          hasMore={journal.state.phase === "ready" && journal.state.hasMore}
          loadingMore={journal.loadingMore}
          moreError={journal.moreError}
          onLoadMore={() => void journal.loadMore()}
        />
      )}
      {!loading && state.phase === "ready" && state.items.length > 0 && state.hasMore && (
        <Button mode="outline" size="m" stretched onClick={() => void loadMore()} loading={state.loadingMore}>
          Показать ещё
        </Button>
      )}
    </div>
  );
}
