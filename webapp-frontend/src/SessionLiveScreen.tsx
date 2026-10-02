import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useRef, useState } from "react";

import {
  backLiveSessionPhase, fetchActiveLiveSession, startLiveBlock,
  type LiveSessionCompleteResponse, type LiveSessionResponse,
} from "./apiV2";
import { BlockTransition } from "./BlockTransition";
import {
  describeBlockPlan, formatDuration, formatLoggedSetSummary, formatNumber, formatTarget, resultInputLabel,
} from "./blockFormat";
import {
  blockSetCounts,
  canGoBackLocal,
  canPauseLocal,
  clearLocalSession,
  clearPauseState,
  completeIfFinishedElsewhere,
  drainQueuedFinish,
  editLastLoggedSet,
  extraSetBlockIndex,
  flushLocalSession,
  isLocalPaused,
  pauseLocalSession,
  resumeLocalSession,
  hasManualTransitions,
  hasPendingWork,
  isGetReadyCueActive,
  initialLocalSession,
  isLocalSessionReusable,
  loadLocalSession,
  localPhaseEndsAtMs,
  nextLocalPhase,
  rebaseLocalSession,
  recordedPlanSet,
  saveLocalSession,
  type LocalLiveSession,
  type LocalPhaseName,
} from "./offlineSession";
import { vibratePhaseEnd, vibrationDelayMs } from "./vibration";
import { cancelScheduledPhaseEndSound, phaseEndCueDelaySeconds, schedulePhaseEndSound } from "./phaseAudio";
import { EFFORT_SCALE, reviewPayload, SET_EFFORT_PROMPT, WORKOUT_COMMENT_MAX } from "./effortScale";
import { backButtonAction, FOCUSABLE_SELECTOR, nextTrapIndex } from "./liveDialog";
import { canStartNextBlock, classifySyncError, finishStatus, type SyncFailure } from "./liveFinish";
import { useLiveFieldFocus } from "./liveFieldFocus";
import { useBackButton } from "./useBackButton";
import { dismissKeyboard } from "./telegramPlatform";
import { useClosingConfirmation } from "./useClosingConfirmation";
import { disableWakeLock, enableWakeLock } from "./wakeLock";
import { isCompleteDecimal, sanitizeDecimalInput } from "./decimalInput";

type Props = {
  initDataRaw: string;
  initialSession: LiveSessionResponse;
  onCompleted: (result: LiveSessionCompleteResponse) => void;
  /** Checkpoint 4B (issue #188) — LiveSessionResponse отдаёт только
   * exercise_id, не имя (проверено дословно по типу). Опционален — лаба
   * (SessionV2Lab.tsx) не передаёт его вовсе, значит name всегда null для
   * неё — та же логика ниже (null = label не показывается) применяется и
   * там, техническое "Упражнение #id" в лабе тоже больше не показывается
   * (integration fix, issue #188) — не отдельное поведение, тот же общий
   * компонент. production-путь (PlanSessionFlow.tsx) передаёт резолвер,
   * построенный один раз из Exercise Library. */
  resolveExerciseName?: (exerciseId: number) => string | null;
  /** Заголовок тренировки верхнего уровня ("Подтягивания"/"Планка") — тот
   * же title, что уже передан в SessionPreScreen/SessionSummaryScreen.
   * Опционален — лаба не передаёт его, "Живая тренировка" остаётся общим
   * заголовком без изменений. */
  title?: string;
  /** R1 — вызывается, когда сервер отдал новое состояние сессии вне обычного
   * потока подходов (явный старт следующего блока): PlanSessionFlow по нему
   * решает, какой экран нужен блоку (обычный/interval). */
  onSessionUpdate?: (session: LiveSessionResponse) => void;
  /** #287: уйти с экрана, пока завершение в очереди (Back/«Выйти»). Данные остаются в IndexedDB и
   * досылаются при следующем открытии (App → fetchActiveLiveSession → этот экран → флаш на mount).
   * Не передан (лаба) — Back при завершении в очереди игнорируется, как раньше. */
  onLeave?: () => void;
};

const LOG_FORM_ID = "live-log-form";
/** #287: сколько ждать досылки чужого завершения из очереди перед показом своей сессии. */
const ORPHAN_DRAIN_TIMEOUT_MS = 5_000;

const PHASE_LABELS: Record<LocalPhaseName, string> = {
  get_ready: "Приготовься",
  go: "Пошёл",
  rest: "Отдых",
  between: "Готово",
  done: "Готово",
};


/**
 * Live-экран сессии (issue #185, раздел 10.8 docs/plan-and-specs.md).
 * Разбор офлайн-архитектуры и почему таймер здесь считается ОДИНАКОВО
 * онлайн/офлайн (не "сервер, пока сеть есть, иначе ничего") — докстринг
 * offlineSession.ts. Каждое действие пользователя (лог подхода, переход
 * фазы, завершение) сразу пишется в IndexedDB (см. saveLocalSession),
 * ПОТОМ, если есть сеть, досылается на сервер; ответ сервера целиком
 * заменяет локальное состояние (offline-session skill: "клиент заменяет
 * локальное состояние серверным, а не мержит вручную").
 */
export function SessionLiveScreen({
  initDataRaw, initialSession, onCompleted, resolveExerciseName, title, onSessionUpdate, onLeave,
}: Props) {
  const [local, setLocalState] = useState<LocalLiveSession | null>(null);
  const localRef = useRef<LocalLiveSession | null>(null);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [syncFailure, setSyncFailure] = useState<SyncFailure | null>(null);
  // Зеркало syncInFlight для рендера (#287): кнопка повтора видна, когда флаша в полёте нет.
  const [syncing, setSyncing] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [value, setValue] = useState("");
  const [effort, setEffort] = useState<string | null>(null);
  const [note, setNote] = useState("");
  // #265: ручное раскрытие/сворачивание панели записи; null — решает фаза
  // (работа: свёрнута, длинный отдых: раскрыта). Сбрасывается при смене фазы.
  const [panelOpen, setPanelOpen] = useState<boolean | null>(null);
  // Review-шаг перед завершением: оценка тренировки целиком + заметка.
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewEffort, setReviewEffort] = useState<string | null>(null);
  const [reviewComment, setReviewComment] = useState("");
  const sheetRef = useRef<HTMLElement | null>(null);
  // #264: форма «+ Ещё подход» (локальный ввод; сам подход живёт в pendingSets).
  const [extraOpen, setExtraOpen] = useState(false);
  const [extraValue, setExtraValue] = useState("");
  const [startingBlock, setStartingBlock] = useState(false);
  const [startBlockError, setStartBlockError] = useState<string | null>(null);
  // #292: ошибка шага «Предыдущий подход» (сеть/сервер) — кнопка остаётся, можно повторить.
  const [backError, setBackError] = useState<string | null>(null);
  // Двойной тап (issue #187, баг 2): быстрый повторный клик по "Готов"/
  // "Готово"/"Завершить" реально шлёт второй запрос до перерисовки кнопки —
  // ref, а не state, чтобы не ждать лишнего рендера между кликами. Хук
  // объявлен здесь, рядом с остальными, а не ближе к использованию —
  // ниже есть ранний `return` (local === null), хуки после него нарушают
  // правило "одинаковый порядок хуков на каждый рендер" (было поймано
  // самим React: "Minified React error #310" при первой попытке).
  // M1 (#285): пока сфокусировано поле ввода, липкий транспорт «отлипает» (live.css).
  const fieldFocused = useLiveFieldFocus();
  const actionInFlight = useRef(false);
  // Single-flight синхронизации (fix/concurrent-set-batch): событие "online"
  // и тап "Завершить" в окне реконнекта раньше запускали ДВА параллельных
  // флаша одного и того же снимка (два одинаковых sets:batch). Сервер к
  // этому устойчив (блокировка сессии + ON CONFLICT, идемпотентный
  // complete), но лишние запросы и повторные переходы фазы от устаревшего
  // снимка не нужны: второй вызов лишь просит ещё один проход после текущего.
  const syncInFlight = useRef<Promise<void> | null>(null);
  const resyncRequested = useRef(false);
  // После успешного complete сессия закрыта: повторные тапы "Завершить" (в окне
  // реконнект-флаша) не должны ни слать второй complete, ни воскрешать
  // очищенный черновик в IndexedDB.
  const completedRef = useRef(false);

  function setLocal(updated: LocalLiveSession) {
    localRef.current = updated;
    setLocalState(updated);
  }

  useEffect(() => {
    let cancelled = false;
    async function init() {
      let existing = await loadLocalSession();
      // #287: в IndexedDB — завершение ДРУГОЙ сессии, оставленное в очереди при уходе с экрана.
      // Этот экран заменит снимок своим — сначала пробуем дослать то (best effort, см. drainQueuedFinish).
      // Не дольше ORPHAN_DRAIN_TIMEOUT_MS: зависший запрос не должен держать экран на «Загружаю…».
      if (existing !== null && existing.serverSessionId !== initialSession.id && existing.completeRequested !== null) {
        await Promise.race([
          drainQueuedFinish(initDataRaw),
          new Promise((resolve) => setTimeout(resolve, ORPHAN_DRAIN_TIMEOUT_MS)),
        ]);
        existing = await loadLocalSession();
      }
      // Старый локальный снимок переиспользуется только если он не отстаёт
      // от сервера (см. isLocalSessionReusable) — иначе состояние прошлого
      // блока протекло бы в следующий.
      const next =
        existing !== null && isLocalSessionReusable(existing, initialSession)
          ? existing
          : initialLocalSession(initialSession.client_session_id, initialSession);
      if (!cancelled) {
        setLocal(next);
        // #287: неотправленное после reload/повторного открытия (подходы, переходы, завершение в
        // очереди) уходит сразу, а не ждёт события `online` (его не будет — сеть уже есть) или
        // следующего действия (при завершении в очереди действий нет вовсе).
        if (hasPendingWork(next)) {
          void syncLocal();
        }
      }
    }
    void init();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSession.id]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  // Возврат из фона (issue #186, раздел 10.8: "при возврате из фона — пересчёт
  // от ends_at, никакого замершего таймера") — не ждём следующего тика
  // setInterval (браузер троттлит его в фоне и может отложить первый тик после
  // возврата), а сразу пересчитываем `now` по реальным часам.
  useEffect(() => {
    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        setNow(Date.now());
      }
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, []);

  // Wake Lock (issue #186, раздел 10.8) — включён на всё время активной сессии,
  // выключается при уходе с этого экрана (завершение или выход).
  useEffect(() => {
    enableWakeLock();
    return () => disableWakeLock();
  }, []);

  async function commitLocal(updated: LocalLiveSession) {
    // localRef обновляется синхронно, ДО await: флаш, завершившийся во время
    // записи в IndexedDB, уже видит это действие и перенесёт его (rebase).
    setLocal(updated);
    if (completedRef.current) {
      return;
    }
    await saveLocalSession(updated);
    // Сеть — НЕ под guardedAction: действие уже зафиксировано локально, а
    // досылку ведёт single-flight syncLocal. Если ждать её здесь, тап
    // "Завершить" во время реконнект-флаша молча отбрасывался бы
    // actionInFlight предыдущего действия.
    void syncLocal();
  }

  /** Досылает localRef.current, не больше одного флаша одновременно. Вызов во
   * время флаша не шлёт второй параллельный запрос, а ставит ещё один проход
   * — по свежему состоянию после ответа сервера — и ждёт его. */
  function syncLocal(): Promise<void> {
    if (syncInFlight.current !== null) {
      resyncRequested.current = true;
      return syncInFlight.current;
    }
    // .finally — всегда асинхронно (микротаска), т.е. ПОСЛЕ присваивания
    // ниже, даже если цикл вышел сразу (офлайн/нечего слать).
    setSyncing(true);
    const run = runSyncLoop().finally(() => {
      syncInFlight.current = null;
      setSyncing(false);
      if (resyncRequested.current && !completedRef.current) {
        // Запрос пришёл уже после последней проверки цикла — не теряем его.
        resyncRequested.current = false;
        void syncLocal();
      }
    });
    syncInFlight.current = run;
    return run;
  }

  async function runSyncLoop(): Promise<void> {
    do {
      resyncRequested.current = false;
      const snapshot = localRef.current;
      if (completedRef.current || snapshot === null || !navigator.onLine || !hasPendingWork(snapshot)) {
        return;
      }
      try {
        const result = await flushLocalSession(initDataRaw, snapshot);
        if (snapshot.completeRequested) {
          completedRef.current = true;
          await clearLocalSession();
          onCompleted(result as LiveSessionCompleteResponse);
          return;
        }
        const fresh = rebaseLocalSession(snapshot, localRef.current ?? snapshot, result as LiveSessionResponse);
        setLocal(fresh);
        await saveLocalSession(fresh);
        setSyncFailure(null);
        if (hasPendingWork(fresh)) {
          resyncRequested.current = true;
        }
      } catch (error) {
        const failure = classifySyncError(error);
        if (snapshot.completeRequested !== null && failure.status === 404) {
          // #287: 404 на флаше завершения — возможно, сессия уже завершена на сервере (ответ
          // прошлого complete потерялся). Тогда это успех, иначе — настоящий отказ.
          try {
            const finished = await completeIfFinishedElsewhere(initDataRaw, snapshot, failure);
            if (finished !== null) {
              completedRef.current = true;
              await clearLocalSession();
              onCompleted(finished);
              return;
            }
          } catch (probeError) {
            setSyncFailure(classifySyncError(probeError));
            return;
          }
        }
        setSyncFailure(failure);
        return;
      }
    } while (resyncRequested.current);
  }

  useEffect(() => {
    function handleOnline() {
      setIsOnline(true);
      void syncLocal();
    }
    function handleOffline() {
      setIsOnline(false);
    }
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initDataRaw]);

  // Источник истины для конца фазы: `ends_at`, присланный сервером для
  // последнего ПОДТВЕРЖДЁННОГО состояния (issue #186), пока локальная фаза не
  // убежала вперёд него оптимистичным переходом (pendingPhaseAdvances > 0) —
  // тогда сервер ещё не знает об этой фазе и её ends_at, используем локальную
  // оценку длительности (offline-session skill: "клиент — источник правды по
  // введённым значениям до синхронизации"). Вычисляется здесь, ДО раннего
  // возврата ниже, чтобы порядок хуков (useEffect для звука) не менялся между
  // рендерами.
  const phaseEndsAtMs = local === null ? null : localPhaseEndsAtMs(local);

  // Звук окончания фазы планируется заранее (issue #186) на собственных часах
  // Web Audio, привязанных к `phaseEndsAtMs` — не к `now`, которое тикает
  // каждую секунду и пересоздавало бы планирование на каждый рендер.
  useEffect(() => {
    if (phaseEndsAtMs === null) {
      cancelScheduledPhaseEndSound();
      return;
    }
    // Вибрация конца фазы (#281): в отличие от звука на часах AudioContext, таймер JS — но
    // только пока экран виден (в фоне снимается вместе со звуком; истёкшая в фоне фаза — без сигнала).
    let vibrationTimer: ReturnType<typeof setTimeout> | null = null;
    function cancelVibration() {
      if (vibrationTimer !== null) {
        clearTimeout(vibrationTimer);
        vibrationTimer = null;
      }
    }
    function schedule() {
      cancelVibration();
      const delay = phaseEndCueDelaySeconds(phaseEndsAtMs as number, Date.now());
      if (delay === null) {
        cancelScheduledPhaseEndSound();
      } else {
        schedulePhaseEndSound(delay);
        const vibrateIn = vibrationDelayMs(phaseEndsAtMs as number, Date.now());
        if (vibrateIn !== null) {
          vibrationTimer = setTimeout(() => {
            vibrationTimer = null;
            if (document.visibilityState === "visible") {
              vibratePhaseEnd();
            }
          }, vibrateIn);
        }
      }
    }
    // #269: в фоне звук не играет, а часы AudioContext могут стоять — уходя в фон
    // снимаем запланированный сигнал, на возврате планируем заново по реальным
    // часам ТОЛЬКО если фаза ещё не закончилась (истёкшая в фоне — без бипа).
    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        schedule();
      } else {
        cancelScheduledPhaseEndSound();
        cancelVibration();
      }
    }
    schedule();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      cancelScheduledPhaseEndSound();
      cancelVibration();
    };
  }, [phaseEndsAtMs]);

  // issue #202/#310 (integration review, H1) — useBackButton должен
  // вызываться безусловно, до любого раннего return: изначально стоял
  // ПОСЛЕ "if (local === null) return ..." ниже — на первом рендере
  // (local ещё null) хук не вызывался вовсе, на следующих — вызывался,
  // классическое нарушение Rules of Hooks (React error #310, найдено
  // живым Playwright-прогоном, воспроизводимо, не флап). handleFinish —
  // function declaration, hoisted, доступна здесь независимо от текстовой
  // позиции своего определения ниже; сама вызывается (через клик) только
  // когда local уже точно не null, поэтому её собственное тело не нужно
  // менять.
  // R1 (инвариант I): значения формы подхода не переживают смену блока/
  // подхода/фазы — ни один локальный ввод предыдущего блока не попадает в
  // следующий (для time-блока поле сразу содержит цель).
  const formBlockIndex = local?.localPhase.blockIndex ?? -1;
  const formSetNumber = local?.localPhase.setNumber ?? -1;
  const formPhaseName = local?.localPhase.phaseName ?? null;
  const formTarget = local?.server.blocks[formBlockIndex]?.targets[formSetNumber - 1] ?? null;
  useEffect(() => {
    // #265: на отдыхе форма — правка только что записанного подхода.
    const cur = localRef.current;
    const last = formPhaseName === "rest" ? cur?.lastLogged ?? null : null;
    // #292: «назад» переоткрыл подход (go) — форма предзаполнена записанным значением; «Готово»
    // перезапишет ту же строку (set_index), ничего не теряется.
    const reopened = formPhaseName === "go" && cur ? recordedPlanSet(cur, formBlockIndex, formSetNumber) : null;
    if (reopened) {
      setValue(reopened.value);
      setEffort(reopened.effort);
      setNote(reopened.note ?? "");
    } else if (last) {
      setValue(last.value);
      setEffort(last.effort ?? null);
      setNote(last.note ?? "");
    } else {
      setValue(
        formTarget !== null && formTarget.unit === "s" && Number(formTarget.value) > 0 ? formatNumber(formTarget.value) : "",
      );
      setEffort(null);
      setNote("");
    }
    setPanelOpen(null);
    setExtraOpen(false);
    setExtraValue("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formBlockIndex, formSetNumber, formPhaseName]);

  // M3 (#285): review-шторка — модальный диалог. Фокус уходит в шторку при открытии, Escape её
  // закрывает (введённые оценка/заметка остаются в состоянии), при закрытии фокус возвращается
  // на кнопку «Завершить» (у неё data-review-opener; кнопки на время шторки размонтируются, поэтому
  // ищем по атрибуту, а не по сохранённому узлу) либо на статус «завершение в очереди».
  useEffect(() => {
    if (!reviewOpen) {
      return;
    }
    sheetRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setReviewOpen(false);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.querySelector<HTMLElement>("[data-review-opener], [data-finish-status]")?.focus();
    };
  }, [reviewOpen]);

  function trapSheetTab(event: React.KeyboardEvent<HTMLElement>) {
    if (event.key !== "Tab") {
      return;
    }
    const nodes = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
    const next = nextTrapIndex(nodes.length, nodes.indexOf(document.activeElement as HTMLElement), event.shiftKey);
    event.preventDefault();
    if (next !== null) {
      nodes[next].focus();
    }
  }

  // Telegram BackButton: с открытой review-шторкой только закрывает её (docs/PROJECT_SPEC.md §12),
  // иначе прежнее поведение — confirm и завершение без review.
  // #287: при завершении в очереди Back уводит с экрана (onLeave) — данные в IndexedDB, не тупик.
  // Пока запрос в полёте — игнор: повторный Back после «Закончить?» иначе уводил бы с экрана за миг
  // до Summary (кнопка «Выйти» в статусе остаётся явным выходом и в этот момент).
  function handleBack() {
    const action = backButtonAction({
      reviewOpen,
      finishing: localRef.current?.completeRequested != null,
      // actionInFlight: завершение фиксируется в IndexedDB, флаш стартует сразу следом — без зазора.
      canLeave: onLeave !== undefined && !actionInFlight.current && syncInFlight.current === null,
    });
    if (action === "close-review") {
      setReviewOpen(false);
    } else if (action === "confirm-finish") {
      handleFinish();
    } else if (action === "leave") {
      onLeave?.();
    }
  }

  useBackButton(handleBack, [local, reviewOpen], true, false); // live-поток без нижней навигации
  // Живая сессия: свайп/«Закрыть» в Telegram спрашивает подтверждение (Bot API 6.2+, #224).
  useClosingConfirmation();

  if (local === null) {
    return <p className="screen-message">Загружаю тренировку…</p>;
  }

  const counts = blockSetCounts(local.server);
  const block = local.server.blocks[local.localPhase.blockIndex] ?? null;
  const totalPending = local.pendingSets.length + local.pendingPhaseAdvances + (local.completeRequested ? 1 : 0);

  // Двойной тап: подтверждено репродукцией (issue #187, баг 2) — быстрый
  // повторный клик по "Готов"/"Готово"/"Завершить" реально шлёт второй
  // запрос до того, как React успевает перерисовать кнопку. Сервер
  // (LiveSessionService.advance_phase, CAS по expected_phase_index) не даёт
  // этому испортить данные — фаза не перескакивает, — но лишний запрос всё
  // равно уходит. actionInFlight объявлен выше, рядом с остальными хуками.

  async function guardedAction(action: () => Promise<void>) {
    if (actionInFlight.current) {
      return;
    }
    actionInFlight.current = true;
    try {
      await action();
    } finally {
      actionInFlight.current = false;
    }
  }

  /** #265: правка подхода с отдыха, ещё не сохранённая кнопкой, не теряется
   * при выходе с отдыха/завершении. */
  function withRestEdit(current: LocalLiveSession): LocalLiveSession {
    // На «Приготовься» форма — правка предыдущего подхода только после явного «Изменить» (panelOpen):
    // иначе поля формы не относятся к lastLogged и не должны его перезаписывать.
    const editing = current.localPhase.phaseName === "rest"
      || (current.localPhase.phaseName === "get_ready" && panelOpen === true);
    return editing
      ? editLastLoggedSet(current, { value, effort, note })
      : current;
  }

  function saveRestEdit() {
    void guardedAction(async () => {
      if (local === null || !isCompleteDecimal(value)) {
        return;
      }
      await commitLocal(withRestEdit(local));
    });
  }

  function advancePhase() {
    void guardedAction(async () => {
      if (local === null) {
        return;
      }
      const edited = withRestEdit(local);
      const newPhase = nextLocalPhase(edited.localPhase, counts, hasManualTransitions(edited.server));
      // Финал-1: с отдыха в «Приготовься» следующего подхода предыдущий подход остаётся доступен для
      // правки (тот же set_index перезапишет строку, данные не теряются); дальше — сбрасывается.
      const keepPrevious = edited.localPhase.phaseName === "rest" && newPhase.phaseName === "get_ready";
      await commitLocal({
        ...clearPauseState(edited),
        lastLogged: keepPrevious ? edited.lastLogged ?? null : null,
        localPhase: newPhase,
        localPhaseEnteredAt: new Date().toISOString(),
        pendingPhaseAdvances: edited.pendingPhaseAdvances + 1,
      });
    });
  }

  // #264: пауза/продолжить — чисто локальные, сразу в снимок (переживают reload).
  function togglePause() {
    void guardedAction(async () => {
      if (local === null) {
        return;
      }
      const nowMs = Date.now();
      await commitLocal(isLocalPaused(local) ? resumeLocalSession(local, nowMs) : pauseLocalSession(local, nowMs));
      setNow(nowMs);
    });
  }

  // #264: «+ Ещё подход» — запись сверх плана в завершённый блок; фазу не двигает.
  function logExtraSet() {
    dismissKeyboard();
    void guardedAction(async () => {
      const index = local === null ? null : extraSetBlockIndex(local);
      const extraBlock = index === null ? null : local?.server.blocks[index] ?? null;
      if (local === null || index === null || extraBlock === null || extraBlock.exercise_id === null) {
        return;
      }
      if (!isCompleteDecimal(extraValue)) {
        return;
      }
      await commitLocal({
        ...local,
        pendingSets: [
          ...local.pendingSets,
          {
            setIndex: local.nextSetIndex, blockIndex: index, exerciseId: extraBlock.exercise_id,
            value: extraValue.trim(), effort: null, note: null, isExtra: true,
          },
        ],
        nextSetIndex: local.nextSetIndex + 1,
      });
      setExtraValue("");
      setExtraOpen(false);
    });
  }

  function logSet() {
    dismissKeyboard();
    void guardedAction(async () => {
      if (local === null || block === null || block.exercise_id === null || !isCompleteDecimal(value)) {
        return;
      }
      const newPhase = nextLocalPhase(local.localPhase, counts, hasManualTransitions(local.server));
      // #292: подход уже записан (после «назад») — тот же set_index перезапишет строку, новый не берём.
      const recorded = recordedPlanSet(local, local.localPhase.blockIndex, local.localPhase.setNumber);
      const logged = {
        setIndex: recorded?.setIndex ?? local.nextSetIndex, blockIndex: local.localPhase.blockIndex,
        exerciseId: block.exercise_id, value: value.trim(), effort, note: note.trim() || null,
      };
      await commitLocal({
        ...clearPauseState(local),
        pendingSets: [...local.pendingSets.filter((entry) => entry.setIndex !== logged.setIndex), logged],
        lastLogged: newPhase.phaseName === "rest" ? logged : null,
        nextSetIndex: recorded ? local.nextSetIndex : local.nextSetIndex + 1,
        localPhase: newPhase,
        localPhaseEnteredAt: new Date().toISOString(),
        pendingPhaseAdvances: local.pendingPhaseAdvances + 1,
      });
      // Форму сбрасывает эффект смены фазы (на отдыхе он подставляет только что
      // записанный подход): сброс здесь, после await, затирал бы его.
    });
  }

  // #292 «Предыдущий подход»: только онлайн и при пустой очереди (canGoBackLocal) — сервер двигает фазу
  // на go предыдущего подхода (SetLog не трогает), ответ целиком заменяет локальный снимок.
  function goBack() {
    void guardedAction(async () => {
      const current = localRef.current ?? local;
      if (current === null || !canGoBackLocal(current, navigator.onLine, syncInFlight.current !== null)) {
        return;
      }
      setBackError(null);
      try {
        // Правка отдыха, ещё не сохранённая кнопкой, не теряется: сначала в очередь, затем досылка.
        const edited = withRestEdit(current);
        if (edited !== current) {
          await commitLocal(edited);
          await syncLocal();
        }
        const base = localRef.current ?? edited;
        if (hasPendingWork(base)) {
          throw new Error(navigator.onLine ? "Не удалось отправить подходы, попробуйте ещё раз" : "Нет сети");
        }
        let next: LiveSessionResponse | null;
        try {
          next = await backLiveSessionPhase(initDataRaw, base.serverSessionId, base.server.phase_index);
        } catch (error) {
          if ((error as { status?: number }).status !== 409) {
            throw error;
          }
          // Устаревшая фаза/граница: перечитываем состояние сервера, без потери данных.
          next = await fetchActiveLiveSession(initDataRaw);
        }
        if (next === null) {
          return;
        }
        const fresh = initialLocalSession(base.clientSessionId, next);
        await saveLocalSession(fresh);
        setLocal(fresh);
        setSyncFailure(null);
        onSessionUpdate?.(next);
      } catch (error) {
        setBackError(error instanceof Error ? error.message : String(error));
      }
    });
  }

  function handleFinish() {
    if (local === null) {
      return;
    }
    if (!window.confirm("Закончить сессию? Что сделано — зачтено, остальное останется в плане.")) {
      return;
    }
    void guardedAction(async () => {
      // Из localRef, не из замыкания рендера: реконнект-флаш мог уже
      // заменить состояние, пока был открыт confirm.
      const current = localRef.current ?? local;
      if (current === null) {
        return;
      }
      await commitLocal({ ...withRestEdit(current), completeRequested: { abandoned: false } });
    });
  }

  // «Завершить» открывает review-шаг (оценка и заметка необязательны); явное
  // «Сохранить и завершить» служит подтверждением вместо window.confirm.
  function submitReview() {
    void guardedAction(async () => {
      const current = localRef.current ?? local;
      if (current === null) {
        return;
      }
      await commitLocal({
        ...withRestEdit(current),
        completeRequested: { abandoned: false, ...reviewPayload(reviewEffort, reviewComment) },
      });
      // M2 (#285): завершение уже зафиксировано локально — шторка закрывается, а статус «завершение
      // в очереди» (finishing ниже) показывает, что тап сработал, даже если сети нет.
      setReviewOpen(false);
    });
  }

  // R1: явный "Начать" следующего блока. Сначала досылаем накопленное (сервер
  // должен быть уже у границы блока), потом стартуем блок; двойной клик
  // отсекается guardedAction, а сам старт идемпотентен на сервере. Ошибка —
  // кнопка остаётся, можно повторить.
  function startNextBlock() {
    void guardedAction(async () => {
      // #287 HIGH 2: завершение в очереди — старт блока сбросил бы снимок вместе с ним и оценкой.
      if (local === null || !canStartNextBlock(localRef.current ?? local)) {
        return;
      }
      setStartingBlock(true);
      setStartBlockError(null);
      try {
        // Через тот же single-flight, что реконнект: иначе "Начать" сразу
        // после возврата сети слал бы второй параллельный флаш.
        await syncLocal();
        const synced = localRef.current ?? local;
        if (!canStartNextBlock(synced)) {
          return;
        }
        if (synced.pendingSets.length > 0 || synced.pendingPhaseAdvances > 0) {
          throw new Error(navigator.onLine ? "Не удалось отправить подходы, попробуйте ещё раз" : "Нет сети");
        }
        const started = await startLiveBlock(initDataRaw, synced.serverSessionId, synced.localPhase.blockIndex);
        await clearLocalSession();
        const fresh = initialLocalSession(synced.clientSessionId, started);
        await saveLocalSession(fresh);
        setLocal(fresh);
        setSyncFailure(null);
        onSessionUpdate?.(started);
      } catch (error) {
        setStartBlockError(error instanceof Error ? error.message : String(error));
      } finally {
        setStartingBlock(false);
      }
    });
  }

  const phaseName = local.localPhase.phaseName;
  const paused = isLocalPaused(local);
  const remaining = paused
    ? Math.max(0, (local.pausedRemainingMs ?? 0) / 1000)
    : phaseEndsAtMs !== null ? Math.max(0, (phaseEndsAtMs - now) / 1000) : null;
  const cueActive = isGetReadyCueActive(phaseName, remaining);
  const restEditable = (phaseName === "rest" || phaseName === "get_ready") && local.lastLogged != null;
  // На «Приготовься» правится предыдущий подход (setNumber уже указывает на следующий).
  const editSetNumber = phaseName === "get_ready" ? Math.max(1, local.localPhase.setNumber - 1) : local.localPhase.setNumber;
  // #286: после записи подхода панель на отдыхе свёрнута до одной строки-сводки («Подход 1: 8 повт.»,
  // «Изменить» раскрывает) — раскрытая под таймером она уходила под липкий транспорт.
  const logPanelOpen = panelOpen ?? false;
  const extraIndex = extraSetBlockIndex(local);
  const extraBlock = extraIndex === null ? null : local.server.blocks[extraIndex];
  const extraCount = extraIndex === null ? 0
    : local.pendingSets.filter((entry) => entry.isExtra && entry.blockIndex === extraIndex).length
      + (extraBlock?.set_logs.filter((log) => log.is_extra).length ?? 0);
  const extraLabel = resultInputLabel(extraBlock?.protocol_type ?? null, null);
  const targetsCount = block?.targets.length ?? 0;
  const targetForSet = block?.targets[local.localPhase.setNumber - 1] ?? null;
  const isMaxBlock = block?.protocol_type === "max_effort";
  const inputLabel = resultInputLabel(block?.protocol_type ?? null, targetForSet);
  // Сводка прошлого подхода: на отдыхе — поля формы (они и есть правка), на «Приготовься» — сама запись.
  const summaryFromRecord = phaseName === "get_ready" && local.lastLogged != null;
  const summaryValue = summaryFromRecord ? local.lastLogged?.value ?? "" : value;
  const summaryEffort = summaryFromRecord ? local.lastLogged?.effort ?? null : effort;
  const summaryNote = summaryFromRecord ? local.lastLogged?.note ?? "" : note;
  function startEditPrevious() {
    const last = local?.lastLogged;
    if (phaseName === "get_ready" && last) {
      setValue(last.value);
      setEffort(last.effort ?? null);
      setNote(last.note ?? "");
    }
    setPanelOpen(true);
  }
  const editLabel = resultInputLabel(block?.protocol_type ?? null, block?.targets[editSetNumber - 1] ?? null);
  // Имя блока — из замороженного снимка тренировки, если он есть, иначе из
  // библиотеки (legacy/STEP). null — имени нет, label не показываем.
  const blockName = (candidate: typeof block): string | null => {
    if (candidate === null) {
      return null;
    }
    if (candidate.exercise_name !== null) {
      return candidate.exercise_name;
    }
    return candidate.exercise_id !== null && resolveExerciseName ? resolveExerciseName(candidate.exercise_id) : null;
  };

  const renderEffortAndNote = () => (
    <div className="live-effort">
      <p className="live-effort-prompt">{SET_EFFORT_PROMPT}</p>
      <EffortChips testId="set-effort" value={effort} onPick={setEffort} />
      <label className="live-field live-note-field">
        <span className="live-field-label">Заметка</span>
        <input
          className="live-field-input live-note-input" type="text" aria-label="Заметка"
          value={note} onChange={(e) => setNote(e.target.value)}
        />
      </label>
    </div>
  );

  const renderValueField = (current: string, onChange: (next: string) => void, label: string) => (
    <label className="live-field">
      <span className="live-field-label">{label}</span>
      <input
        className="live-field-input live-value-input" aria-label={label} type="text" inputMode="decimal" enterKeyHint="done" autoComplete="off"
        value={current} onChange={(e) => onChange(sanitizeDecimalInput(e.target.value))}
      />
    </label>
  );

  // Прогресс подходов (точки): в работе текущий подход — «идёт», на отдыхе/после
  // плана текущий уже сделан.
  const doneSets = phaseName === "rest" || phaseName === "done" ? local.localPhase.setNumber : local.localPhase.setNumber - 1;
  const showPips = targetsCount > 1 && targetsCount <= 12;
  const heroTarget = phaseName === "go" && remaining === null && targetForSet !== null ? formatTarget(targetForSet) : null;
  // «Завершить»: в шапке, пока идёт тренировка; когда план выполнен — главное действие транспорта.
  const finishIsPrimary = phaseName === "done";
  // M2: завершение поставлено в очередь (ждёт сети/ответа сервера) — управление тренировкой скрыто.
  const finishing = local.completeRequested !== null;
  // #287: статус завершения — без тупиков (liveFinish.ts): офлайн ждёт сеть, онлайн без запроса в
  // полёте всегда даёт «Отправить ещё раз», Back/«Выйти» уводят с экрана.
  const finish = finishStatus({ finishing, online: isOnline, syncing, failure: syncFailure });
  const showTransport = !reviewOpen && !extraOpen && phaseName !== "between" && !finishing;
  const canPause = canPauseLocal(local) || paused;
  // #292: шаг назад показан на всех фазах плеера; недоступен (disabled) офлайн, при очереди и на границе блока.
  const showSetNav = block !== null || phaseName === "done";
  const canBack = canGoBackLocal(local, isOnline, syncing);

  return (
    <div
      className="live-screen" data-phase={phaseName} data-paused={paused ? "true" : undefined}
      data-field-focus={fieldFocused ? "true" : undefined}
    >
      <header className="live-header">
        <div className="live-header-text">
          <p className="live-eyebrow">Живая тренировка</p>
          {title && <p className="live-workout-title">{title}</p>}
        </div>
        {!reviewOpen && !finishIsPrimary && !finishing && (
          <button type="button" className="live-finish" data-review-opener onClick={() => setReviewOpen(true)}>
            Завершить
          </button>
        )}
      </header>
      {!isOnline && <p className="gap-banner">Нет сети — подходы сохраняются локально и уйдут батчем при подключении.</p>}
      {/* Пока завершение в очереди, о досылке говорит только статус ниже (действий нет — «повторю
          при следующем действии» было бы неправдой, #287 LOW 8). */}
      {!finishing && isOnline && totalPending > 0 && <p className="gap-banner">Не синхронизировано: {totalPending}. Досылаю…</p>}
      {!finishing && syncFailure && (
        <p className="gap-banner">Не удалось синхронизировать: {syncFailure.message}. Повторю при следующем действии.</p>
      )}
      {finishing && (
        <div
          className="gap-banner live-finish-status" data-testid="finish-pending" data-finish-status data-state={finish}
          role="status" tabIndex={-1}
        >
          <p>{finishStatusText(finish, syncFailure)}</p>
          {(finish === "retry" || finish === "rejected") && (
            <button type="button" className="live-link-button" data-testid="finish-retry" onClick={() => void syncLocal()}>
              Отправить ещё раз
            </button>
          )}
          {onLeave !== undefined && (
            <button type="button" className="live-link-button" data-testid="finish-leave" onClick={onLeave}>
              Выйти
            </button>
          )}
        </div>
      )}

      {phaseName !== "between" && block !== null && phaseName !== "done" && (() => {
        // name=null значит "имени действительно нет" (internal STEP-роль,
        // Checkpoint 3C) — не "Упражнение #id" и не выдуманный термин.
        // UX-1: «что сейчас делаю» — крупным блоком над таймером (раньше мелкий
        // серый текст, налезавший на рамку карточки фазы).
        const name = blockName(block);
        const planText = targetForSet !== null ? formatTarget(targetForSet) : null;
        // Вторая цифра счётчика — цель подхода, где она есть (повторения / время); у max-блока нет.
        const counterTarget =
          !isMaxBlock && targetForSet !== null && Number(targetForSet.value) > 0
            ? targetForSet.unit === "reps"
              ? { value: formatNumber(targetForSet.value), label: "Повт" }
              : targetForSet.unit === "s"
                ? { value: formatDuration(Number(targetForSet.value)), label: "Время" }
                : null
            : null;
        return (
          <div className="live-now" data-testid="live-now">
            {name !== null && <p className="live-exercise">{name}</p>}
            <div className="live-counter" data-testid="live-counter" aria-hidden="true">
              <div className="live-counter-cell">
                <span className="live-counter-num">
                  {local.localPhase.setNumber}<span className="live-counter-total"> / {targetsCount}</span>
                </span>
                <span className="live-counter-label">{isMaxBlock ? "Попытка" : "Подход"}</span>
              </div>
              {counterTarget !== null && (
                <div className="live-counter-cell">
                  <span className="live-counter-num">{counterTarget.value}</span>
                  <span className="live-counter-label">{counterTarget.label}</span>
                </div>
              )}
            </div>
            <p className="live-target">
              {isMaxBlock ? "Попытка" : "Подход"} {local.localPhase.setNumber}/{targetsCount}
              {isMaxBlock ? " · Максимум" : planText !== null ? ` · Цель: ${planText}` : ""}
            </p>
            {showPips && (
              <div className="live-pips" aria-hidden="true">
                {Array.from({ length: targetsCount }, (_, i) => (
                  <span
                    key={i}
                    className={i < doneSets ? "live-pip live-pip-done" : i === doneSets ? "live-pip live-pip-current" : "live-pip"}
                  />
                ))}
              </div>
            )}
            {phaseName === "get_ready" && (
              <p className="live-plan">
                {describeBlockPlan(block.protocol_type, block.targets, block.interval_config)}
              </p>
            )}
          </div>
        );
      })()}
      {phaseName === "between" && block !== null && !finishing ? (
        <BlockTransition
          block={block} name={blockName(block)} starting={startingBlock} error={startBlockError}
          onStart={startNextBlock}
        />
      ) : (
      <div className={`phase-panel phase-card-${phaseName}`}>
        <h2 className="phase-panel-label">{PHASE_LABELS[phaseName]}</h2>
        {remaining !== null && (
          <p className={`timer-duration-label phase-timer-${phaseName}`}>{formatDuration(remaining)}</p>
        )}
        {heroTarget !== null && <p className="live-hero-target phase-timer-go">{heroTarget}</p>}
        {cueActive && (
          <p className="get-ready-cue" data-testid="get-ready-cue">
            Приготовься · <span data-testid="get-ready-countdown">{Math.ceil(remaining ?? 0)}</span>
          </p>
        )}
        {phaseName === "done" && (
          <p className="live-done-note">Все подходы плана выполнены — можно завершить сессию.</p>
        )}
      </div>
      )}

      {phaseName === "go" && block !== null && !finishing && (
        <section
          className="live-panel live-log-panel"
          data-testid="log-panel" data-state={logPanelOpen ? "expanded" : "collapsed"}
        >
          <h3 className="live-panel-title">Внести подход</h3>
          {/* aria-label дублирует подпись намеренно: accessible name инпута —
              именно aria-label, как и в WorkoutScreen.tsx/BackdateForm.tsx. */}
          {/* Enter/«Go» в поле = тот же защищённый обработчик, что у «Готово» (кнопка транспорта
              привязана к форме атрибутом form — implicit submission работает и с заметкой). */}
          <form id={LOG_FORM_ID} onSubmit={(event) => { event.preventDefault(); logSet(); }}>
            {renderValueField(value, setValue, inputLabel.label)}
            {inputLabel.hint !== null && (
              <p className="live-hint" data-testid="result-hint">{inputLabel.hint}</p>
            )}
            {logPanelOpen && renderEffortAndNote()}
          </form>
          <button
            type="button" className="live-link-button" data-testid="log-panel-toggle"
            aria-expanded={logPanelOpen} onClick={() => setPanelOpen(!logPanelOpen)}
          >
            {logPanelOpen ? "Свернуть" : "Оценка и заметка"}
          </button>
        </section>
      )}

      {restEditable && !finishing && (
        <section
          className={logPanelOpen ? "live-panel live-log-panel" : "live-panel live-log-panel live-log-collapsed"}
          data-testid="log-panel" data-state={logPanelOpen ? "expanded" : "collapsed"}
        >
          {logPanelOpen ? (
            <>
              <h3 className="live-panel-title">{`Подход ${editSetNumber}: результат`}</h3>
              <form onSubmit={(event) => { event.preventDefault(); if (isCompleteDecimal(value)) { saveRestEdit(); } }}>
                {renderValueField(value, setValue, editLabel.label)}
                {renderEffortAndNote()}
                <Button className="live-save" size="l" stretched mode="bezeled" type="submit" disabled={!isCompleteDecimal(value)}>
                  Сохранить подход
                </Button>
              </form>
              <button
                type="button" className="live-link-button" data-testid="log-panel-toggle"
                aria-expanded={true} onClick={() => setPanelOpen(false)}
              >
                Свернуть
              </button>
            </>
          ) : (
            <div className="live-summary-row">
              <p className="live-summary-line" data-testid="log-panel-summary">
                {formatLoggedSetSummary(editSetNumber, summaryValue, editLabel.label)}
                {summaryEffort !== null ? ` · оценка ${summaryEffort}` : ""}{summaryNote.trim() !== "" ? ` · ${summaryNote.trim()}` : ""}
              </p>
              <button
                type="button" className="live-link-button live-edit-button" data-testid="log-panel-toggle"
                aria-expanded={false} aria-label="Изменить" onClick={startEditPrevious}
              >
                <span aria-hidden="true">✎</span> Изменить
              </button>
            </div>
          )}
        </section>
      )}

      {extraIndex !== null && extraOpen && !finishing && (
        <section className="live-panel">
          <h3 className="live-panel-title">Ещё подход</h3>
          <form data-testid="extra-set-form" onSubmit={(event) => { event.preventDefault(); logExtraSet(); }}>
            {renderValueField(extraValue, setExtraValue, extraLabel.label)}
            <Button className="live-save" size="l" stretched type="submit" disabled={!isCompleteDecimal(extraValue)}>
              Записать
            </Button>
            <Button className="live-save" size="l" stretched mode="outline" type="button" onClick={() => setExtraOpen(false)}>
              Отмена
            </Button>
          </form>
        </section>
      )}
      {extraIndex !== null && !extraOpen && extraCount > 0 && (
        <p className="live-extra-count" data-testid="extra-count">Дополнительных подходов: {extraCount}</p>
      )}

      {showTransport && (
        <div className="live-transport">
          {phaseName === "get_ready" && (
            <Button className="live-primary" size="l" stretched onClick={advancePhase}>
              Готов
            </Button>
          )}
          {phaseName === "go" && block !== null && (
            <Button className="live-primary" size="l" stretched type="submit" form={LOG_FORM_ID} disabled={!isCompleteDecimal(value)}>
              Готово
            </Button>
          )}
          {phaseName === "rest" && (
            <Button className="live-primary" size="l" stretched onClick={advancePhase}>
              Пропустить отдых
            </Button>
          )}
          {finishIsPrimary && (
            <Button className="live-primary" size="l" stretched data-review-opener onClick={() => setReviewOpen(true)}>
              Завершить
            </Button>
          )}
          {(canPause || extraIndex !== null || showSetNav) && (
            <div className="live-secondary-row">
              {showSetNav && (
                <Button
                  className="live-secondary live-set-nav" size="m" mode="bezeled" data-testid="set-prev"
                  aria-label="Предыдущий подход" disabled={!canBack} onClick={goBack}
                  title={canBack ? undefined : isOnline ? "Нет предыдущего подхода или идёт синхронизация" : "Нужна сеть"}
                >
                  <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">
                    <path d="M7 5v14M18 6l-8 6 8 6V6z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </Button>
              )}
              {canPause && (
                <Button
                  className="live-secondary" size="m" stretched mode="bezeled" data-testid="pause-toggle"
                  onClick={togglePause}
                >
                  {paused ? "Продолжить" : "Пауза"}
                </Button>
              )}
              {extraIndex !== null && (
                <Button
                  className="live-secondary" size="m" stretched mode="bezeled" data-testid="extra-set-button"
                  onClick={() => setExtraOpen(true)}
                >
                  + Ещё подход
                </Button>
              )}
            </div>
          )}
        </div>
      )}

      {backError !== null && showTransport && (
        <p className="live-hint" role="alert" data-testid="set-prev-error">{backError}</p>
      )}

      {reviewOpen && (
        <div className="live-sheet-layer">
          <div className="live-sheet-backdrop" onClick={() => setReviewOpen(false)} aria-hidden="true" />
          <section
            ref={sheetRef} tabIndex={-1} onKeyDown={trapSheetTab}
            className="live-sheet" role="dialog" aria-modal="true" aria-label="Итог тренировки" data-testid="workout-review"
          >
            <div className="live-sheet-handle" aria-hidden="true" />
            <h3 className="live-sheet-title">Как прошла тренировка?</h3>
            <p className="live-hint">Что сделано — зачтено, остальное останется в плане.</p>
            <EffortChips
              testId="workout-effort" value={reviewEffort}
              onPick={(next) => setReviewEffort(reviewEffort === next ? null : next)}
            />
            <label className="live-field live-note-field">
              <span className="live-field-label">Заметка</span>
              <textarea
                className="live-field-input live-note-textarea" aria-label="Заметка к тренировке" rows={3}
                maxLength={WORKOUT_COMMENT_MAX} value={reviewComment}
                onChange={(e) => setReviewComment(e.target.value)}
              />
            </label>
            <Button className="live-primary" size="l" stretched onClick={submitReview}>
              Сохранить и завершить
            </Button>
            <Button className="live-secondary live-sheet-back" size="m" stretched mode="plain" onClick={() => setReviewOpen(false)}>
              Назад
            </Button>
          </section>
        </div>
      )}
    </div>
  );
}

/** Текст статуса «завершение в очереди» (#287). Везде, кроме «отправляю», сказано, что результат
 * сохранён на устройстве: ничего не удаляется, даже если сервер завершение отверг. */
function finishStatusText(status: ReturnType<typeof finishStatus>, failure: SyncFailure | null): string {
  switch (status) {
    case "offline":
      return "Тренировка завершена: результат сохранён на устройстве и отправится, когда появится сеть.";
    case "sending":
      return "Завершаю тренировку…";
    case "rejected":
      return failure?.kind === "auth"
        ? `${failure.message} Результат сохранён на устройстве и отправится после повторного открытия.`
        : `Сервер не принял завершение: ${failure?.message ?? "ошибка"}. Результат сохранён на этом устройстве.`;
    default:
      return failure !== null
        ? `Не удалось отправить завершение: ${failure.message}. Результат сохранён на устройстве.`
        : "Завершение ещё не отправлено. Результат сохранён на устройстве.";
  }
}

/** Шкала усилия 1–5: цифра + слово, одна строка из пяти сегментов (подход и тренировка). */
function EffortChips({ testId, value, onPick }: { testId: string; value: string | null; onPick: (value: string) => void }) {
  return (
    <div className="live-chips" data-testid={testId}>
      {EFFORT_SCALE.map((option) => (
        <button
          key={option.value}
          type="button"
          className={value === option.value ? "live-chip live-chip-active" : "live-chip"}
          aria-pressed={value === option.value}
          onClick={() => onPick(option.value)}
        >
          <span className="effort-num">{option.value}</span>
          <span className="effort-word">{option.label}</span>
        </button>
      ))}
    </div>
  );
}
