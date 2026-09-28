import { Button, Input, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useRef, useState } from "react";

import { startLiveBlock, type LiveSessionCompleteResponse, type LiveSessionResponse } from "./apiV2";
import { BlockTransition } from "./BlockTransition";
import { describeBlockPlan, formatDuration, formatNumber, formatTarget } from "./blockFormat";
import {
  blockSetCounts,
  clearLocalSession,
  flushLocalSession,
  hasManualTransitions,
  initialLocalSession,
  isLocalSessionReusable,
  loadLocalSession,
  localPhaseDurationSeconds,
  nextLocalPhase,
  saveLocalSession,
  type LocalLiveSession,
  type LocalPhaseName,
} from "./offlineSession";
import { cancelScheduledPhaseEndSound, schedulePhaseEndSound } from "./phaseAudio";
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

const EFFORT_OPTIONS = ["1", "2", "3", "4", "5"];

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
    await saveLocalSession(updated);
    setLocal(updated);
    if (!navigator.onLine) {
      return;
    }
    try {
      const result = await flushLocalSession(initDataRaw, updated);
      if (updated.completeRequested) {
        await clearLocalSession();
        onCompleted(result as LiveSessionCompleteResponse);
        return;
      }
      const fresh = initialLocalSession(updated.clientSessionId, result as LiveSessionResponse);
      await saveLocalSession(fresh);
      setLocal(fresh);
      setSyncError(null);
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : String(error));
    }
  }

  useEffect(() => {
    function handleOnline() {
      setIsOnline(true);
      const current = localRef.current;
      if (
        current !== null &&
        (current.pendingSets.length > 0 || current.pendingPhaseAdvances > 0 || current.completeRequested !== null)
      ) {
        void commitLocal(current);
      }
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
  const phaseEndsAtMs = ((): number | null => {
    if (local === null) {
      return null;
    }
    const isSyncedWithServer = local.pendingPhaseAdvances === 0;
    const serverEndsAt = isSyncedWithServer ? local.server.phase.ends_at : null;
    if (serverEndsAt !== null) {
      return new Date(serverEndsAt).getTime();
    }
    const duration = localPhaseDurationSeconds(
      local.localPhase.phaseName, local.server.blocks[local.localPhase.blockIndex]?.rest_seconds,
    );
    return duration !== null ? new Date(local.localPhaseEnteredAt).getTime() + duration * 1000 : null;
  })();

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
      if (local === null) {
        return;
      }
      await commitLocal({ ...local, completeRequested: { abandoned: false } });
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
        if (local.pendingSets.length > 0 || local.pendingPhaseAdvances > 0) {
          await flushLocalSession(initDataRaw, { ...local, completeRequested: null });
        }
        const started = await startLiveBlock(initDataRaw, local.serverSessionId, local.localPhase.blockIndex);
        await clearLocalSession();
        const fresh = initialLocalSession(local.clientSessionId, started);
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
  const isTimeBlock = block?.protocol_type === "time_sets" || (block !== null && targetForSet?.unit === "s");
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

      {phaseName === "between" && block !== null ? (
        <BlockTransition
          block={block} name={blockName(block)} starting={startingBlock} error={startBlockError}
          onStart={startNextBlock}
        />
      ) : (
      <Section className={`block-section phase-card-${phaseName}`} header={PHASE_LABELS[phaseName]}>
        {remaining !== null && (
          <p className={`timer-duration-label phase-timer-${phaseName}`}>{formatDuration(remaining)}</p>
        )}
        {block !== null && phaseName !== "done" && (() => {
          // name=null значит "имени действительно нет" (internal STEP-роль,
          // Checkpoint 3C) — не "Упражнение #id" и не выдуманный термин.
          const name = blockName(block);
          const planText = targetForSet !== null ? formatTarget(targetForSet) : null;
          return (
            <>
              <p className="block-subtitle">
                {name !== null && `${name} · `}
                {isMaxBlock ? "Попытка" : "Подход"} {local.localPhase.setNumber}/{targetsCount}
                {isMaxBlock ? " · Максимум" : planText !== null ? ` · Цель: ${planText}` : ""}
              </p>
              {phaseName === "get_ready" && (
                <p className="block-subtitle">
                  {describeBlockPlan(block.protocol_type, block.targets, block.interval_config)}
                </p>
              )}
            </>
          );
        })()}
      </Section>
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
            header={isTimeBlock ? "Секунды" : isMaxBlock ? "Повторений" : "Результат"}
            aria-label={isTimeBlock ? "Секунды" : isMaxBlock ? "Повторений" : "Результат"}
            type="number"
            inputMode="decimal"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <div className="effort-segment-row">
            {EFFORT_OPTIONS.map((option) => (
              <Button
                key={option}
                size="s"
                mode={effort === option ? "filled" : "outline"}
                onClick={() => setEffort(option)}
              >
                {option}
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

      <Button className="action-button" size="l" stretched mode="outline" onClick={handleFinish}>
        Завершить
      </Button>
    </div>
  );
}
