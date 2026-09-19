import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  completeLiveSession,
  fetchActiveLiveSession,
  type LiveSessionCompleteResponse,
  type LiveSessionResponse,
  type ProgramInclusionResponseV2,
  type SessionResponseV2,
} from "./apiV2";
import { clearLocalSession } from "./offlineSession";
import { DashboardV2Screen } from "./DashboardV2Screen";
import { SessionEditScreen } from "./SessionEditScreen";
import { SessionJournalScreen } from "./SessionJournalScreen";
import { SessionLiveScreen } from "./SessionLiveScreen";
import { SessionPreScreen } from "./SessionPreScreen";
import { SessionSummaryScreen } from "./SessionSummaryScreen";

type Props = {
  initDataRaw: string;
  onGoToWorkout: () => void;
};

type SubScreen =
  | { kind: "dashboard" }
  | { kind: "pre" }
  | { kind: "live"; session: LiveSessionResponse }
  | { kind: "summary"; result: LiveSessionCompleteResponse }
  | { kind: "journal" }
  | { kind: "edit"; session: SessionResponseV2; inclusion: ProgramInclusionResponseV2 };

/**
 * Контейнер экспериментальной вкладки v2 "Сессия" (issue #185, волна 5) —
 * пред-экран/live/итог/журнал-правка живут здесь одним деревом, за той же
 * admin-only вкладкой "dashboardV2" (App.tsx), что и раньше DashboardV2Screen
 * — старая схема остаётся источником истины до волны cutover (см.
 * .claude/skills/multi-program/SKILL.md), эта вкладка — испытательный
 * стенд, не замена реального "workout" для обычных пользователей.
 */
export function SessionV2Lab({ initDataRaw, onGoToWorkout }: Props) {
  const [screen, setScreen] = useState<SubScreen>({ kind: "dashboard" });
  const [activeSession, setActiveSession] = useState<LiveSessionResponse | null | undefined>(undefined);

  useEffect(() => {
    if (screen.kind !== "dashboard") {
      return;
    }
    let cancelled = false;
    fetchActiveLiveSession(initDataRaw)
      .then((session) => {
        if (!cancelled) {
          setActiveSession(session);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setActiveSession(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, screen.kind]);

  async function handleAbandonActive() {
    if (activeSession === null || activeSession === undefined) {
      return;
    }
    await completeLiveSession(initDataRaw, activeSession.id, true);
    await clearLocalSession();
    setActiveSession(null);
  }

  if (screen.kind === "pre") {
    return (
      <SessionPreScreen
        initDataRaw={initDataRaw}
        onGoToWorkout={onGoToWorkout}
        onStarted={(session) => setScreen({ kind: "live", session })}
      />
    );
  }

  if (screen.kind === "live") {
    return (
      <SessionLiveScreen
        initDataRaw={initDataRaw}
        initialSession={screen.session}
        onCompleted={(result) => setScreen({ kind: "summary", result })}
      />
    );
  }

  if (screen.kind === "summary") {
    return <SessionSummaryScreen result={screen.result} onClose={() => setScreen({ kind: "dashboard" })} />;
  }

  if (screen.kind === "journal") {
    return (
      <SessionJournalScreen
        initDataRaw={initDataRaw}
        onEdit={(session, inclusion) => setScreen({ kind: "edit", session, inclusion })}
        onBack={() => setScreen({ kind: "dashboard" })}
      />
    );
  }

  if (screen.kind === "edit") {
    return (
      <SessionEditScreen
        initDataRaw={initDataRaw}
        session={screen.session}
        inclusion={screen.inclusion}
        onDone={() => setScreen({ kind: "journal" })}
      />
    );
  }

  return (
    <div>
      {activeSession && (
        <div className="gap-banner">
          <p>Есть незавершённая тренировка.</p>
          <Button size="s" onClick={() => setScreen({ kind: "live", session: activeSession })}>
            Продолжить
          </Button>{" "}
          <Button size="s" mode="outline" onClick={() => void handleAbandonActive()}>
            Завершить
          </Button>
        </div>
      )}
      <DashboardV2Screen initDataRaw={initDataRaw} onGoToWorkout={onGoToWorkout} />
      <Button className="action-button" size="l" stretched onClick={() => setScreen({ kind: "pre" })}>
        Начать тренировку (v2)
      </Button>
      <Button className="action-button" size="l" stretched mode="outline" onClick={() => setScreen({ kind: "journal" })}>
        Журнал (v2)
      </Button>
    </div>
  );
}
