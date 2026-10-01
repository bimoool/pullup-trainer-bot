import { Button, Input, Section, Textarea } from "@telegram-apps/telegram-ui";
import { useEffect, useRef, useState } from "react";

import { startLiveBlock, type LiveSessionCompleteResponse, type LiveSessionResponse } from "./apiV2";
import { BlockTransition } from "./BlockTransition";
import { describeBlockPlan, formatDuration, formatNumber, formatTarget, resultInputLabel } from "./blockFormat";
import {
  blockSetCounts,
  clearLocalSession,
  flushLocalSession,
  hasManualTransitions,
  hasPendingWork,
  initialLocalSession,
  isLocalSessionReusable,
  loadLocalSession,
  localPhaseEndsAtMs,
  nextLocalPhase,
  rebaseLocalSession,
  saveLocalSession,
  type LocalLiveSession,
  type LocalPhaseName,
} from "./offlineSession";
import { cancelScheduledPhaseEndSound, schedulePhaseEndSound } from "./phaseAudio";
import { EFFORT_SCALE, reviewPayload, SET_EFFORT_PROMPT, WORKOUT_COMMENT_MAX, WORKOUT_EFFORT_PROMPT } from "./effortScale";
import { useBackButton } from "./useBackButton";
import { disableWakeLock, enableWakeLock } from "./wakeLock";

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
};

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
  initDataRaw, initialSession, onCompleted, resolveExerciseName, title, onSessionUpdate,
}: Props) {
  const [local, setLocalState] = useState<LocalLiveSession | null>(null);
  const localRef = useRef<LocalLiveSession | null>(null);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [value, setValue] = useState("");
  const [effort, setEffort] = useState<string | null>(null);
  const [note, setNote] = useState("");
  // Review-шаг перед завершением: оценка тренировки целиком + заметка.
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewEffort, setReviewEffort] = useState<string | null>(null);
  const [reviewComment, setReviewComment] = useState("");
  const [startingBlock, setStartingBlock] = useState(false);
  const [startBlockError, setStartBlockError] = useState<string | null>(null);
  // Двойной тап (issue #187, баг 2): быстрый повторный клик по "Готов"/
  // "Готово"/"Завершить" реально шлёт второй запрос до перерисовки кнопки —
  // ref, а не state, чтобы не ждать лишнего рендера между кликами. Хук
  // объявлен здесь, рядом с остальными, а не ближе к использованию —
  // ниже есть ранний `return` (local === null), хуки после него нарушают
  // правило "одинаковый порядок хуков на каждый рендер" (было поймано
  // самим React: "Minified React error #310" при первой попытке).
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
      const existing = await loadLocalSession();
      // Старый локальный снимок переиспользуется только если он не отстаёт
      // от сервера (см. isLocalSessionReusable) — иначе состояние прошлого
      // блока протекло бы в следующий.
      const next =
        existing !== null && isLocalSessionReusable(existing, initialSession)
          ? existing
          : initialLocalSession(initialSession.client_session_id, initialSession);
      if (!cancelled) {
        setLocal(next);
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
    const run = runSyncLoop().finally(() => {
      syncInFlight.current = null;
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
        setSyncError(null);
        if (hasPendingWork(fresh)) {
          resyncRequested.current = true;
        }
      } catch (error) {
        setSyncError(error instanceof Error ? error.message : String(error));
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
    schedulePhaseEndSound((phaseEndsAtMs - Date.now()) / 1000);
    return () => cancelScheduledPhaseEndSound();
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
    setValue(
      formTarget !== null && formTarget.unit === "s" && Number(formTarget.value) > 0 ? formatNumber(formTarget.value) : "",
    );
    setEffort(null);
    setNote("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formBlockIndex, formSetNumber, formPhaseName]);

  useBackButton(handleFinish, [local]);

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

  function advancePhase() {
    void guardedAction(async () => {
      if (local === null) {
        return;
      }
      const newPhase = nextLocalPhase(local.localPhase, counts, hasManualTransitions(local.server));
      await commitLocal({
        ...local,
        localPhase: newPhase,
        localPhaseEnteredAt: new Date().toISOString(),
        pendingPhaseAdvances: local.pendingPhaseAdvances + 1,
      });
    });
  }

  function logSet() {
    void guardedAction(async () => {
      if (local === null || block === null || block.exercise_id === null || value.trim() === "") {
        return;
      }
      const newPhase = nextLocalPhase(local.localPhase, counts, hasManualTransitions(local.server));
      await commitLocal({
        ...local,
        pendingSets: [
          ...local.pendingSets,
          {
            setIndex: local.nextSetIndex, blockIndex: local.localPhase.blockIndex, exerciseId: block.exercise_id,
            value: value.trim(), effort, note: note.trim() || null,
          },
        ],
        nextSetIndex: local.nextSetIndex + 1,
        localPhase: newPhase,
        localPhaseEnteredAt: new Date().toISOString(),
        pendingPhaseAdvances: local.pendingPhaseAdvances + 1,
      });
      setValue("");
      setEffort(null);
      setNote("");
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
      await commitLocal({ ...current, completeRequested: { abandoned: false } });
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
        ...current,
        completeRequested: { abandoned: false, ...reviewPayload(reviewEffort, reviewComment) },
      });
    });
  }

  // R1: явный "Начать" следующего блока. Сначала досылаем накопленное (сервер
  // должен быть уже у границы блока), потом стартуем блок; двойной клик
  // отсекается guardedAction, а сам старт идемпотентен на сервере. Ошибка —
  // кнопка остаётся, можно повторить.
  function startNextBlock() {
    void guardedAction(async () => {
      if (local === null) {
        return;
      }
      setStartingBlock(true);
      setStartBlockError(null);
      try {
        // Через тот же single-flight, что реконнект: иначе "Начать" сразу
        // после возврата сети слал бы второй параллельный флаш.
        await syncLocal();
        const synced = localRef.current ?? local;
        if (synced.pendingSets.length > 0 || synced.pendingPhaseAdvances > 0) {
          throw new Error(navigator.onLine ? "Не удалось отправить подходы, попробуйте ещё раз" : "Нет сети");
        }
        const started = await startLiveBlock(initDataRaw, synced.serverSessionId, synced.localPhase.blockIndex);
        await clearLocalSession();
        const fresh = initialLocalSession(synced.clientSessionId, started);
        await saveLocalSession(fresh);
        setLocal(fresh);
        setSyncError(null);
        onSessionUpdate?.(started);
      } catch (error) {
        setStartBlockError(error instanceof Error ? error.message : String(error));
      } finally {
        setStartingBlock(false);
      }
    });
  }

  const phaseName = local.localPhase.phaseName;
  const remaining = phaseEndsAtMs !== null ? Math.max(0, (phaseEndsAtMs - now) / 1000) : null;
  const targetsCount = block?.targets.length ?? 0;
  const targetForSet = block?.targets[local.localPhase.setNumber - 1] ?? null;
  const isMaxBlock = block?.protocol_type === "max_effort";
  const inputLabel = resultInputLabel(block?.protocol_type ?? null, targetForSet);
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

  return (
    <div>
      <p className="plan-title">Живая тренировка</p>
      {title && <p className="block-subtitle">{title}</p>}
      {!isOnline && <p className="gap-banner">Нет сети — подходы сохраняются локально и уйдут батчем при подключении.</p>}
      {isOnline && totalPending > 0 && <p className="gap-banner">Не синхронизировано: {totalPending}. Досылаю…</p>}
      {syncError && <p className="gap-banner">Не удалось синхронизировать: {syncError}. Повторю при следующем действии.</p>}

      {phaseName !== "between" && block !== null && phaseName !== "done" && (() => {
        // name=null значит "имени действительно нет" (internal STEP-роль,
        // Checkpoint 3C) — не "Упражнение #id" и не выдуманный термин.
        // UX-1: «что сейчас делаю» — крупным блоком над таймером (раньше мелкий
        // серый текст, налезавший на рамку карточки фазы).
        const name = blockName(block);
        const planText = targetForSet !== null ? formatTarget(targetForSet) : null;
        return (
          <div className="live-now" data-testid="live-now">
            {name !== null && <p className="live-exercise">{name}</p>}
            <p className="live-target">
              {isMaxBlock ? "Попытка" : "Подход"} {local.localPhase.setNumber}/{targetsCount}
              {isMaxBlock ? " · Максимум" : planText !== null ? ` · Цель: ${planText}` : ""}
            </p>
            {phaseName === "get_ready" && (
              <p className="block-subtitle">
                {describeBlockPlan(block.protocol_type, block.targets, block.interval_config)}
              </p>
            )}
          </div>
        );
      })()}
      {phaseName === "between" && block !== null ? (
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
      </div>
      )}

      {phaseName === "get_ready" && (
        <Button className="action-button" size="l" stretched onClick={advancePhase}>
          Готов
        </Button>
      )}

      {phaseName === "go" && block !== null && (
        <Section className="block-section" header="Внести подход">
          {/* aria-label дублирует header намеренно — telegram-ui's Input
              рендерит header-подпись СНАРУЖИ своего <label> (см. разбор
              FormInput.js), она не становится accessible name инпута; та же
              причина, по которой WorkoutScreen.tsx/BackdateForm.tsx везде
              используют явный aria-label, не полагаются на header. */}
          <Input
            header={inputLabel.label}
            aria-label={inputLabel.label}
            type="number"
            inputMode="decimal"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          {inputLabel.hint !== null && (
            <p className="block-subtitle" data-testid="result-hint">{inputLabel.hint}</p>
          )}
          <p className="block-subtitle">{SET_EFFORT_PROMPT}</p>
          <div className="effort-segment-row effort-labelled" data-testid="set-effort">
            {EFFORT_SCALE.map((option) => (
              <Button
                key={option.value}
                size="s"
                mode={effort === option.value ? "filled" : "outline"}
                aria-pressed={effort === option.value}
                onClick={() => setEffort(option.value)}
              >
                <span className="effort-num">{option.value}</span>
                <span className="effort-word">{option.label}</span>
              </Button>
            ))}
          </div>
          <Input header="Заметка" aria-label="Заметка" value={note} onChange={(e) => setNote(e.target.value)} />
          <Button className="action-button" size="l" stretched disabled={value.trim() === ""} onClick={logSet}>
            Готово
          </Button>
        </Section>
      )}

      {phaseName === "rest" && (
        <Button className="action-button" size="l" stretched onClick={advancePhase}>
          Пропустить отдых
        </Button>
      )}

      {phaseName === "done" && (
        <p className="screen-message">Все подходы плана выполнены — можно завершить сессию.</p>
      )}

      {reviewOpen ? (
        <Section className="block-section" header="Как прошла тренировка?">
          <div data-testid="workout-review">
            <p className="block-subtitle">
              {WORKOUT_EFFORT_PROMPT} Что сделано — зачтено, остальное останется в плане.
            </p>
            <div className="effort-segment-row effort-labelled" data-testid="workout-effort">
              {EFFORT_SCALE.map((option) => (
                <Button
                  key={option.value}
                  size="s"
                  mode={reviewEffort === option.value ? "filled" : "outline"}
                  aria-pressed={reviewEffort === option.value}
                  onClick={() => setReviewEffort(reviewEffort === option.value ? null : option.value)}
                >
                  <span className="effort-num">{option.value}</span>
                  <span className="effort-word">{option.label}</span>
                </Button>
              ))}
            </div>
            <Textarea
              header="Заметка"
              aria-label="Заметка к тренировке"
              maxLength={WORKOUT_COMMENT_MAX}
              value={reviewComment}
              onChange={(e) => setReviewComment(e.target.value)}
            />
            <Button className="action-button" size="l" stretched onClick={submitReview}>
              Сохранить и завершить
            </Button>
            <Button className="action-button" size="l" stretched mode="outline" onClick={() => setReviewOpen(false)}>
              Назад
            </Button>
          </div>
        </Section>
      ) : (
        <Button className="action-button" size="l" stretched mode="outline" onClick={() => setReviewOpen(true)}>
          Завершить
        </Button>
      )}
    </div>
  );
}
