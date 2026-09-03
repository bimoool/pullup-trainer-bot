import { useEffect, useState } from "react";

import { fetchProfile, type ProfileResponse } from "./api";

type Props = { initDataRaw: string };

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; profile: ProfileResponse };

/** Вкладка "Профиль" Mini App (issue #45, часть 3) — сознательно узкий
 * первый шаг: подписка, монеты, число тренировок/ачивок, дни с последней
 * тренировки. Полный профиль (рост/вес/таймзона/список ачивок текстом)
 * остаётся только в боте (app/bot/handlers/menu.py::render_profile) — сюда
 * можно добавлять поля по одному, когда понадобится, не всё сразу. */
export function ProfileScreen({ initDataRaw }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const profile = await fetchProfile(initDataRaw);
        if (!cancelled) {
          setState({ phase: "ready", profile });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю профиль…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить профиль: {state.message}</p>;
  }

  const { profile } = state;
  if (!profile.is_onboarded) {
    return <p className="screen-message">Онбординг ещё не пройден. Начни его в боте.</p>;
  }

  return (
    <div>
      <p className="plan-title">Профиль</p>

      <div className="profile-card">
        <p>Подписка: {profile.subscription_status_label}</p>
        <p>
          {profile.days_since_last_workout === null
            ? "Тренировок пока не было."
            : profile.days_since_last_workout === 0
              ? "Последняя тренировка — сегодня."
              : `Последняя тренировка: ${profile.days_since_last_workout} дн. назад.`}
        </p>
      </div>

      <div className="stat-grid">
        <div className="stat-tile">
          <div className="stat-value">{profile.workouts_count}</div>
          <div className="stat-label">Тренировок</div>
        </div>
        <div className="stat-tile">
          <div className="stat-value">{profile.achievements_count}</div>
          <div className="stat-label">Ачивок</div>
        </div>
        <div className="stat-tile">
          <div className="stat-value">{profile.coins_balance}</div>
          <div className="stat-label">Монет</div>
        </div>
      </div>
    </div>
  );
}
