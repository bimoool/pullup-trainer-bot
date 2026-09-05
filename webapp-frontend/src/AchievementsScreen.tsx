import { Button } from "@telegram-apps/telegram-ui";

import type { AchievementItem } from "./api";

type Props = { achievements: AchievementItem[]; onBack: () => void };

/** "2026-09-03" -> "03.09.2026" — тот же формат даты, что HistoryScreen. */
function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  return `${day}.${month}.${year}`;
}

/** Список разблокированных ачивок с датами (issue #66, п.1) — открывается
 * тапом по счётчику "Ачивок" на "Профиле" (ProfileScreen.tsx), тот же приём
 * навигации внутри вкладки, что HistoryEditForm поверх HistoryScreen — не
 * отдельная вкладка нижнего меню ради одного маленького экрана. Данные уже
 * загружены вместе с профилем (GET /api/profile, app.domain.achievements.
 * ACHIEVEMENT_LABELS на бэкенде) — отдельного запроса здесь нет. */
export function AchievementsScreen({ achievements, onBack }: Props) {
  return (
    <div>
      <p className="plan-title">Ачивки</p>

      {achievements.length === 0 ? (
        <p className="screen-message">Пока нет ни одной ачивки.</p>
      ) : (
        <div className="history-list">
          {achievements.map((achievement) => (
            <div className="history-card" key={achievement.code}>
              <p>{achievement.label}</p>
              <p className="hint">{formatDate(achievement.unlocked_at)}</p>
            </div>
          ))}
        </div>
      )}

      <Button mode="outline" size="m" stretched onClick={onBack}>
        ← Назад
      </Button>
    </div>
  );
}
