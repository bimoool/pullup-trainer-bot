import { useEffect, useState } from "react";

import { type ExerciseResponseV2, fetchExercises, type LiveSessionCompleteResponse, type LiveSessionResponse } from "./apiV2";
import { IntervalLiveScreen } from "./IntervalLiveScreen";
import { LiveEngineScreen } from "./LiveEngineScreen";
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
  /** «Начать» на Workout Detail — свободная сессия своей тренировки (без PlanItem). */
  workoutId?: number;
  onClose: () => void;
  /** #300: «Открыть подписку» с экрана «нужна подписка» (курс без действующей подписки). */
  onOpenSubscription?: () => void;
  /** «Назад» с предэкрана (до старта): по умолчанию как onClose; App возвращает на Workout Detail (#277). */
  onCancel?: () => void;
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
export function PlanSessionFlow({ initDataRaw, planItemIds, manual, title, initialSession, workoutId, onClose, onCancel, onOpenSubscription }: Props) {
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

  function resolveExerciseName(exerciseId: number): string | null {
    return libraryExercises.find((exercise) => exercise.id === exerciseId)?.name ?? null;
  }

  if (screen.kind === "pre") {
    return (
      <SessionPreScreen
        initDataRaw={initDataRaw}
        planItemIds={planItemIds}
        manual={manual}
        title={title}
        workoutId={workoutId}
        onOpenSubscription={onOpenSubscription}
        onStarted={(session) => setScreen({ kind: "live", session })}
        onGoToWorkout={onCancel ?? onClose}
      />
    );
  }

  if (screen.kind === "live") {
    // Phase B2 (issue #215) — interval получает отдельную rendering
    // branch (раздел 13), не встраивается в SessionLiveScreen.tsx's
    // offline-очередь/ручной ввод подхода, которые interval не нужны.
    // Единственный сигнал — screen.session.interval !== null, тот же
    // признак, что backend уже кладёт в LiveSessionResponse только для
    // interval-блоков (Phase B1).
    //
    // R1: смешанная тренировка идёт блок за блоком; interval — только когда
    // ТЕКУЩИЙ блок interval И начат (session.interval — серверная проекция),
    // не начатый interval-блок показывается interstitial'ом внутри
    // SessionLiveScreen. key по (сессия, блок) — экран и его локальное
    // состояние пересоздаются на каждом блоке, ничего не протекает дальше.
    if (screen.session.engine_version === 2 && screen.session.engine) {
      // issue #306: Live Engine v2 — один экран на всю тренировку (подходы, STEP-блоки и интервалы идут
      // через один движок; блоки сменяются сами по дедлайну, без interstitial «Начать»).
      return (
        <LiveEngineScreen
          key={screen.session.id}
          initDataRaw={initDataRaw}
          initialSession={screen.session}
          onCompleted={(result) => setScreen({ kind: "summary", result })}
          onLeave={onClose}
          resolveExerciseName={resolveExerciseName}
          title={title}
        />
      );
    }
    // Движок v1 (сессии, начатые до #306, engine_version = 1) — прежние экраны без изменений.
    const blockKey = `${screen.session.id}-${screen.session.current_block_index}`;
    const onSessionUpdate = (session: LiveSessionResponse) => setScreen({ kind: "live", session });
    if (screen.session.interval !== null) {
      return (
        <IntervalLiveScreen
          key={blockKey}
          initDataRaw={initDataRaw}
          initialSession={screen.session}
          onCompleted={(result) => setScreen({ kind: "summary", result })}
          onAdvanced={onSessionUpdate}
          title={title}
        />
      );
    }
    return (
      <SessionLiveScreen
        key={blockKey}
        initDataRaw={initDataRaw}
        initialSession={screen.session}
        onCompleted={(result) => setScreen({ kind: "summary", result })}
        onSessionUpdate={onSessionUpdate}
        resolveExerciseName={resolveExerciseName}
        title={title}
        // #287: при завершении в очереди Back/«Выйти» уводят к вкладкам; очередь остаётся в
        // IndexedDB, при следующем открытии App возобновит сессию (fetchActiveLiveSession) и
        // SessionLiveScreen дошлёт завершение на mount.
        onLeave={onClose}
      />
    );
  }

  return (
    <SessionSummaryScreen
      result={screen.result} onClose={onClose} resolveExerciseName={resolveExerciseName} title={title}
    />
  );
}
