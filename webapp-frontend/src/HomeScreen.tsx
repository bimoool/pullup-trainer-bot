import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchDashboard, type DashboardResponse } from "./api";
import { streakValue } from "./DashboardScreen";

type Props = {
  initDataRaw: string;
  /** Открывает вкладку "Тренировка" (не пункт нижнего меню — issue #183,
   * волна 5b, см. App.tsx). WorkoutScreen сам показывает нужное состояние
   * (форма, "не готов", бэкдейт и т.п.) — Главная не дублирует эту логику. */
  onOpenWorkout: () => void;
  /** Открывает вкладку "Планы" — туда переехал прежний Dashboard (issue #175,
   * волна 4) целиком, со сводкой недели и статусом готовности. */
  onOpenPlans: () => void;
};

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; dashboard: DashboardResponse };

/**
 * Стартовый экран Mini App (issue #183, волна 5b; référence — crimpd-reference
 * skill, "Пять вкладок... Главная-каталог"). Каталог курсов — волна 6, здесь
 * ещё нет ни одного курса, поэтому вместо заглушки, похожей на рабочий
 * каталог, — честный текст. Полная сводка (сколько тренировок, статус
 * готовности, кнопка "Начать тренировку") осталась на "Планах"
 * (DashboardScreen.tsx) как есть — здесь только компактный виджет недели.
 */
export function HomeScreen({ initDataRaw, onOpenWorkout, onOpenPlans }: Props) {
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
        <div className="stat-grid">
          <div className="stat-tile">
            <div className="stat-value">{state.dashboard.workouts_count}</div>
            <div className="stat-label">Тренировок всего</div>
          </div>
          <div className="stat-tile">
            <div className="stat-value">
              {streakValue(state.dashboard.streak, state.dashboard.workouts_count)}
            </div>
            <div className="stat-label">Подряд без перерыва</div>
          </div>
        </div>
      )}

      <Button className="action-button" size="l" stretched onClick={onOpenPlans}>
        К плану
      </Button>

      <Button className="action-button" size="l" stretched mode="outline" onClick={onOpenWorkout}>
        Тренировка
      </Button>

      <p className="section-title">Курсы</p>
      {/* Каталог — волна 6 (issue #183 обсуждение). Секция сознательно не
          рисует карточки-заглушки, похожие на рабочий каталог — только
          честный текст о том, что курсов пока нет. */}
      <p className="screen-message">
        Каталог курсов появится здесь позже. Пока доступна тренировка по подтягиваниям — открой её на вкладке
        «Планы» или кнопкой выше.
      </p>
    </div>
  );
}
