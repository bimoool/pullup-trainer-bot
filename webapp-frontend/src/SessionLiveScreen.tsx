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

type Props = {
  initDataRaw: string;
  initialSession: LiveSessionResponse;
  onCompleted: (result: LiveSessionCompleteResponse) => void;
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
export function SessionLiveScreen({ initDataRaw, initialSession, onCompleted }: Props) {
  const [local, setLocalState] = useState<LocalLiveSession | null>(null);
  const localRef = useRef<LocalLiveSession | null>(null);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [value, setValue] = useState("");
  const [effort, setEffort] = useState<string | null>(null);
  const [note, setNote] = useState("");

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

  if (local === null) {
    return <p className="screen-message">Загружаю тренировку…</p>;
  }

  const counts = blockSetCounts(local.server);
  const block = local.server.blocks[local.localPhase.blockIndex] ?? null;
  const totalPending = local.pendingSets.length + local.pendingPhaseAdvances + (local.completeRequested ? 1 : 0);

  function advancePhase() {
    if (local === null) {
      return;
    }
    const newPhase = nextLocalPhase(local.localPhase, counts);
    void commitLocal({
      ...local,
      localPhase: newPhase,
      localPhaseEnteredAt: new Date().toISOString(),
      pendingPhaseAdvances: local.pendingPhaseAdvances + 1,
    });
  }

  function logSet() {
    if (local === null || block === null || block.exercise_id === null || value.trim() === "") {
      return;
    }
    const newPhase = nextLocalPhase(local.localPhase, counts);
    void commitLocal({
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
  }

  function handleFinish() {
    if (local === null) {
      return;
    }
    if (!window.confirm("Закончить сессию? Что сделано — зачтено, остальное останется в плане.")) {
      return;
    }
    void commitLocal({ ...local, completeRequested: { abandoned: false } });
  }

  const phaseName = local.localPhase.phaseName;
  const duration = localPhaseDurationSeconds(phaseName);
  const elapsed = (now - new Date(local.localPhaseEnteredAt).getTime()) / 1000;
  const remaining = duration !== null ? Math.max(0, duration - elapsed) : null;
  const targetsCount = block?.targets.length ?? 0;
  const targetForSet = block?.targets[local.localPhase.setNumber - 1] ?? null;

  return (
    <div>
      <p className="plan-title">Живая тренировка</p>
      {!isOnline && <p className="gap-banner">Нет сети — подходы сохраняются локально и уйдут батчем при подключении.</p>}
      {isOnline && totalPending > 0 && <p className="gap-banner">Не синхронизировано: {totalPending}. Досылаю…</p>}
      {syncError && <p className="gap-banner">Не удалось синхронизировать: {syncError}. Повторю при следующем действии.</p>}

      <Section className="block-section" header={PHASE_LABELS[phaseName]}>
        {remaining !== null && <p className="timer-duration-label">{formatSeconds(remaining)}</p>}
        {block !== null && phaseName !== "done" && (
          <p className="block-subtitle">
            Упражнение #{block.exercise_id} · Подход {local.localPhase.setNumber}/{targetsCount}
            {targetForSet ? ` · Цель: ${targetForSet.value} ${targetForSet.unit}` : ""}
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
