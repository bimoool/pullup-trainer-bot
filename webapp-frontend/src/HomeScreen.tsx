import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState, type ReactNode } from "react";

import { fetchDashboard, type DashboardResponse } from "./api";
import { STATUS_MESSAGES } from "./WorkoutScreen";

type Props = {
  initDataRaw: string;
  /** Кнопка "Начать тренировку"/"Перейти к тренировке" ниже не вводит
   * тренировку сама (issue #175, п.1 — стартовый экран не может быть
   * открытой тренировкой) — только переключает на вкладку "Тренировка",
   * где уже живёт вся логика статусов/форм (WorkoutScreen.tsx). */
  onGoToWorkout: () => void;
};

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; dashboard: DashboardResponse };

export function HomeScreen({ initDataRaw, onGoToWorkout }: Props) {
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

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить главный экран: {state.message}</p>;
  }

  const { dashboard } = state;

  let statusCard: ReactNode;
  if (dashboard.status === "ready") {
    const ctaLabel = dashboard.is_first_workout ? "Начать первую тренировку" : "Начать тренировку";
    statusCard = (
      <div className="profile-card">
        <p className="section-title">Сегодня</p>
        {dashboard.is_first_workout && (
          <p>
            Это будет твоя первая тренировка — на следующем экране расскажем, какой снаряд нужен по результату
            замера.
          </p>
        )}
        {dashboard.is_deload_a && (
          <p>Сегодня — ежемесячный тест на максимум блока на объём, без обычной цели.</p>
        )}
        {dashboard.is_heavy_b && (
          <p>Сегодня — тяжёлая тренировка блока Б: фиксированные повторения на повышенном весе.</p>
        )}
        {dashboard.is_gap_rollback && <p>Был перерыв — цель блока A немного снижена, это нормально.</p>}
        {!dashboard.is_first_workout && !dashboard.is_deload_a && (
          <p>
            {`Блок A — цель ${dashboard.target_a} (${dashboard.equipment_a?.label ?? "снаряд не выбран"}), ` +
              `блок Б — цель ${dashboard.target_b} (${dashboard.equipment_b?.label ?? "снаряд не выбран"}).`}
          </p>
        )}
        <Button className="action-button" size="l" stretched onClick={onGoToWorkout}>
          {ctaLabel}
        </Button>
      </div>
    );
  } else {
    const message = STATUS_MESSAGES[dashboard.status] ?? `Форма пока недоступна (статус: ${dashboard.status}).`;
    statusCard = (
      <div className="profile-card">
        <p className="section-title">Сегодня</p>
        {dashboard.status === "too_early" ? (
          <p>
            {"Сегодня — день отдыха."}
            {dashboard.ready_at && ` Следующая тренировка доступна с ${dashboard.ready_at}.`}
          </p>
        ) : (
          <p>{message}</p>
        )}
        <Button className="action-button" size="l" stretched onClick={onGoToWorkout}>
          Перейти к тренировке
        </Button>
      </div>
    );
  }

  const statsCard = (
    <div className="profile-card">
      <p className="section-title">Статистика</p>
      {dashboard.total_workouts === 0 ? (
        <p>Пока нет ни одной тренировки — начни первую, чтобы здесь появилась статистика.</p>
      ) : (
        <>
          <p>{`Всего тренировок: ${dashboard.total_workouts}`}</p>
          <p>{`За последние 7 дней: ${dashboard.workouts_last_7_days}`}</p>
          <p>
            {dashboard.streak_days >= 2
              ? `🔥 Серия без пропусков: ${dashboard.streak_days} тренировок подряд`
              : "Серии тренировок подряд без пропусков пока нет."}
          </p>
          <p>
            {dashboard.days_since_last_workout === 0
              ? "Последняя тренировка — сегодня."
              : `Последняя тренировка: ${dashboard.days_since_last_workout} дн. назад.`}
          </p>
        </>
      )}
    </div>
  );

  return (
    <div>
      <p className="plan-title">Главная</p>
      {statusCard}
      {statsCard}
    </div>
  );
}
