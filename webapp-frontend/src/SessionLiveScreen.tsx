import { Button, Input, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useRef, useState } from "react";

import type { LiveSessionCompleteResponse, LiveSessionResponse } from "./apiV2";
import {
  blockSetCounts,
  flushLocalSession,
  initialLocalSession,
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
   * (SessionV2Lab.tsx) не передаёт его, получает прежний фолбэк
   * "Упражнение #id" без изменений; production-путь (PlanSessionFlow.tsx)
   * передаёт резолвер, построенный один раз из Exercise Library. */
  resolveExerciseName?: (exerciseId: number) => string;
};

const PHASE_LABELS: Record<LocalPhaseName, string> = {
  get_ready: "Приготовься",
  go: "Пошёл",
  rest: "Отдых",
  done: "Готово",
};

const EFFORT_OPTIONS = ["1", "2", "3", "4", "5"];

function formatSeconds(total: number): string {
  const clamped = Math.max(0, Math.round(total));
  const minutes = Math.floor(clamped / 60);
  const seconds = clamped % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

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
export function SessionLiveScreen({ initDataRaw, initialSession, onCompleted, resolveExerciseName }: Props) {
  const [local, setLocalState] = useState<LocalLiveSession | null>(null);
  const localRef = useRef<LocalLiveSession | null>(null);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [value, setValue] = useState("");
  const [effort, setEffort] = useState<string | null>(null);
  const [note, setNote] = useState("");
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
      const next =
        existing !== null && existing.serverSessionId === initialSession.id
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
    const duration = localPhaseDurationSeconds(local.localPhase.phaseName);
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
      const newPhase = nextLocalPhase(local.localPhase, counts);
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
      const newPhase = nextLocalPhase(local.localPhase, counts);
      await commitLocal({
        ...local,
        pendingSets: [
          ...local.pendingSets,
          { setIndex: local.nextSetIndex, exerciseId: block.exercise_id, value: value.trim(), effort, note: note.trim() || null },
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

  // issue #202: Telegram BackButton — переиспользует существующий handleFinish
  // (тот же confirm-диалог "Закончить сессию?", что у кнопки "Завершить" —
  // не создаёт вторую бизнес-логику выхода, подключается к существующей)
  useBackButton(handleFinish, [local]);

  const phaseName = local.localPhase.phaseName;
  const remaining = phaseEndsAtMs !== null ? Math.max(0, (phaseEndsAtMs - now) / 1000) : null;
  const targetsCount = block?.targets.length ?? 0;
  const targetForSet = block?.targets[local.localPhase.setNumber - 1] ?? null;

  return (
    <div>
      <p className="plan-title">Живая тренировка</p>
      {!isOnline && <p className="gap-banner">Нет сети — подходы сохраняются локально и уйдут батчем при подключении.</p>}
      {isOnline && totalPending > 0 && <p className="gap-banner">Не синхронизировано: {totalPending}. Досылаю…</p>}
      {syncError && <p className="gap-banner">Не удалось синхронизировать: {syncError}. Повторю при следующем действии.</p>}

      <Section className={`block-section phase-card-${phaseName}`} header={PHASE_LABELS[phaseName]}>
        {remaining !== null && (
          <p className={`timer-duration-label phase-timer-${phaseName}`}>{formatSeconds(remaining)}</p>
        )}
        {block !== null && phaseName !== "done" && (
          <p className="block-subtitle">
            {block.exercise_id !== null && resolveExerciseName
              ? resolveExerciseName(block.exercise_id)
              : `Упражнение #${block.exercise_id}`}
            {" "}· Подход {local.localPhase.setNumber}/{targetsCount}
            {targetForSet !== null && Number(targetForSet.value) > 0
              ? ` · Цель: ${targetForSet.value} ${targetForSet.unit}`
              : ""}
          </p>
        )}
      </Section>

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
            header="Результат"
            aria-label="Результат"
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
