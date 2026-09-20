import { useEffect, useState } from "react";

import { type ExerciseResponseV2, fetchExercises, type LiveSessionCompleteResponse, type LiveSessionResponse } from "./apiV2";
import { SessionLiveScreen } from "./SessionLiveScreen";
import { SessionPreScreen } from "./SessionPreScreen";
import { SessionSummaryScreen } from "./SessionSummaryScreen";

type Props = {
  initDataRaw: string;
  /** Явный набор PlanItem пользовательской карточки на "Планах" —
   * (program_inclusion_id, day_of_week) группа, для "Подтягиваний" это оба
   * внутренних PlanItem (Блок A + Блок Б) одной ProgramInclusion, для
   * manual-группы — id одной ручной строки ("Планка"/"Отжимания"). */
  planItemIds: number[];
  /** Checkpoint 4B (issue #188) — manual PlanItem (program_inclusion_id=
   * NULL) не имеет ProgramInclusion, весь STEP/readiness-путь
   * SessionPreScreen для него неприменим — см. докстринг там же. */
  manual: boolean;
  /** Заголовок карточки — то же group.title, что уже показывает
   * DashboardScreen.tsx, не пересчитывается заново. */
  title: string;
  /** Reload/recovery (issue #188, checkpoint 4A раздел 10) — если на
   * момент монтирования уже есть STARTED-сессия (App.tsx проверяет через
   * fetchActiveLiveSession при загрузке, тем же вызовом, что уже
   * использует SessionV2Lab.tsx), открываемся сразу на "live", минуя
   * pre-screen и повторный вызов startLiveSession — иначе пользователь
   * после reload попадал бы на Главную с потерянной живой сессией, а
   * повторный клик "Начать" породил бы вторую TrainingSession (свежий
   * client_session_id не совпадёт с исходным). */
  initialSession: LiveSessionResponse | null;
  onClose: () => void;
};

type SubScreen =
  | { kind: "pre" }
  | { kind: "live"; session: LiveSessionResponse }
  | { kind: "summary"; result: LiveSessionCompleteResponse };

/**
 * Checkpoint 4A/4B (issue #188) — production-путь входа в живую сессию из
 * реальной PlanWeek-карточки на "Планах", НЕ через admin-стенд
 * SessionV2Lab.tsx. Переиспользует те же production-capable экраны
 * (SessionPreScreen/SessionLiveScreen/SessionSummaryScreen), что и лаба —
 * но без DashboardV2Screen/SessionJournalScreen/SessionEditScreen: тем
 * остаться dev/admin-стендом, эта же машина состояний — только
 * pre -> live -> summary, без лишнего.
 */
export function PlanSessionFlow({ initDataRaw, planItemIds, manual, title, initialSession, onClose }: Props) {
  const [screen, setScreen] = useState<SubScreen>(
    initialSession !== null ? { kind: "live", session: initialSession } : { kind: "pre" },
  );
  // Checkpoint 4B (issue #188, раздел 4) — LiveSessionResponse отдаёт
  // только exercise_id, не имя. Одна загрузка библиотеки на весь flow
  // (не по одной на экран), тот же GET /exercises, что уже подключён в
  // picker'е DashboardScreen.tsx — не новый endpoint, не лишний запрос.
  const [libraryExercises, setLibraryExercises] = useState<ExerciseResponseV2[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchExercises(initDataRaw)
      .then((exercises) => {
        if (!cancelled) {
          setLibraryExercises(exercises);
        }
      })
      .catch(() => {
        // молчаливо — при неудаче резолвер просто не найдёт имя, экраны
        // сами откатятся на фолбэк "Упражнение #id", это не должно рвать
        // сессию.
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  function resolveExerciseName(exerciseId: number): string {
    return libraryExercises.find((exercise) => exercise.id === exerciseId)?.name ?? `Упражнение #${exerciseId}`;
  }

  if (screen.kind === "pre") {
    return (
      <SessionPreScreen
        initDataRaw={initDataRaw}
        planItemIds={planItemIds}
        manual={manual}
        title={title}
        onStarted={(session) => setScreen({ kind: "live", session })}
        onGoToWorkout={onClose}
      />
    );
  }

  if (screen.kind === "live") {
    return (
      <SessionLiveScreen
        initDataRaw={initDataRaw}
        initialSession={screen.session}
        onCompleted={(result) => setScreen({ kind: "summary", result })}
        resolveExerciseName={resolveExerciseName}
      />
    );
  }

  return <SessionSummaryScreen result={screen.result} onClose={onClose} resolveExerciseName={resolveExerciseName} />;
}
