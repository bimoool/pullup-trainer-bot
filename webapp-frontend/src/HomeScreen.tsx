import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchDashboard, type DashboardResponse } from "./api";
import { STATUS_MESSAGES } from "./WorkoutScreen";

type Props = {
  initDataRaw: string;
  /** Открывает форму тренировки тем же способом, что и у "Планов"
   * (DashboardScreen.tsx) — переключает нижнюю вкладку на "workout", сама
   * форма не дублируется (см. App.tsx). */
  onOpenWorkout: () => void;
};

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; dashboard: DashboardResponse };

/** Волна 5b (issue #183) — "Главная" вместо бывшего стартового "Dashboard":
 * полная сводка (стрик, счётчики) переехала во вкладку "Планы" как есть
 * (DashboardScreen.tsx, без изменений), здесь остаётся только компактный
 * виджет "на этой неделе" — статус готовности + быстрый переход к
 * тренировке, тот же текст/логика статуса, что и там (независимая копия,
 * как и весь остальной текст интерфейса в этом проекте — см. docstring
 * WORK_SETS_GROWTH_NOTICES в WorkoutScreen.tsx). Каталога ещё нет (волна 6,
 * crimpd-reference skill) — ниже честный текст об этом, не имитация
 * рабочего каталога. */
export function HomeScreen({ initDataRaw, onOpenWorkout }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchDashboard(initDataRaw)
      .then((dashboard) => {
        if (!cancelled) {
          setState({ phase: "ready", dashboard });
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
  }, [initDataRaw]);

  return (
    <div>
      <p className="plan-title">Главная</p>

      {state.phase === "loading" && <p className="screen-message">Загружаю…</p>}
      {state.phase === "error" && <p className="screen-message">Не удалось загрузить: {state.message}</p>}

      {state.phase === "ready" && (
        <div className="profile-card">
          <p className="section-title">На этой неделе</p>
          {(() => {
            const { dashboard } = state;
            const isReady = dashboard.status === "ready";
            let statusText: string;
            if (isReady && dashboard.is_first_workout) {
              statusText = "Это будет твоя первая тренировка — сначала подберём снаряд по замеру.";
            } else if (isReady) {
              statusText = "Готов к тренировке.";
            } else {
              statusText = STATUS_MESSAGES[dashboard.status] ?? `Статус: ${dashboard.status}`;
            }
            return (
              <>
                <p>{statusText}</p>
                <Button className="action-button" size="l" stretched onClick={onOpenWorkout}>
                  {isReady ? "Начать тренировку" : "Открыть «Тренировку»"}
                </Button>
              </>
            );
          })()}
        </div>
      )}

      {/* Каталог программ — волна 6, ещё не сделан (multi-program skill).
          Честное пустое состояние вместо заглушки, которая выглядела бы как
          рабочий каталог (issue #183). */}
      <div className="profile-card">
        <p className="section-title">Каталог программ</p>
        <p className="screen-message">
          Скоро здесь появится каталог курсов и комплексов упражнений. Пока доступна только программа подтягиваний —
          она во вкладке «Планы».
        </p>
      </div>
    </div>
  );
}
