import { Button, Cell, Placeholder, Section } from "@telegram-apps/telegram-ui";

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
 * ACHIEVEMENT_LABELS на бэкенде) — отдельного запроса здесь нет.
 * `Section`/`Cell`/`Placeholder` вместо `.history-list`/`.history-card`/
 * `.screen-message` (issue #142, пилот миграции на @telegram-apps/telegram-ui) —
 * первый экран, задающий базовый паттерн для остальных списков. */
export function AchievementsScreen({ achievements, onBack }: Props) {
  return (
    <div>
      <Section header="Ачивки">
        {achievements.length === 0 ? (
          <Placeholder description="Пока нет ни одной ачивки." />
        ) : (
          achievements.map((achievement) => (
            <Cell key={achievement.code} hint={formatDate(achievement.unlocked_at)} multiline>
              {achievement.label}
            </Cell>
          ))
        )}
      </Section>

      <Button mode="outline" size="m" stretched onClick={onBack}>
        ← Назад
      </Button>
    </div>
  );
}
