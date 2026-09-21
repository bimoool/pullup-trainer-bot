import { Button } from "@telegram-apps/telegram-ui";

import type { ProgramResponseV2 } from "./apiV2";
import { useBackButton } from "./useBackButton";

type Props = {
  program: ProgramResponseV2;
  included: boolean;
  adding: boolean;
  addError: string | null;
  onAdd: () => void;
  onBack: () => void;
};

/** `ProgramStructureType` (`app/domain/multi_program.py`) человеческим
 * языком — сам enum технический (recurring/fixed/single_lesson), показывать
 * его как есть в UI нельзя. Раздел про интерфейс на Detail-экране (issue
 * #192) прямо требует "структуру человеческим языком", это единственная
 * точка перевода на фронтенде. */
const STRUCTURE_TYPE_LABELS: Record<string, string> = {
  recurring: "Повторяющаяся программа (по неделям)",
  fixed: "Программа на фиксированный срок",
  single_lesson: "Разовое занятие",
};

/**
 * Program Detail (issue #192) — отдельный экран каталога, открывается тапом
 * по карточке на Главной (HomeScreen.tsx), не modal и не разворачивание
 * карточки на месте: тот же приём "swap внутри вкладки", что уже использует
 * AchievementsScreen поверх ProfileScreen (issue #66/#125) — HomeScreen
 * держит `selectedProgramId` и делает ранний return на этот компонент вместо
 * каталога, "Назад" возвращает список тем же локальным состоянием, не
 * браузерной историей.
 *
 * Только реальные поля каталога программ (name/goal/structure_type,
 * `ProgramResponseV2` в apiV2.ts) — equipment/duration/levels в API сейчас
 * нет, честное отсутствие вместо выдумки (issue #192). Кнопка "Добавить в план"/"В плане ✓" — та же, что
 * раньше жила прямо на карточке Главной (Capability A, issue #188), просто
 * переехала сюда; действие (`onAdd`) и состояние (`included`/`adding`)
 * остаются в HomeScreen, чтобы возврат назад сразу показывал актуальный
 * статус без повторного запроса.
 */
export function ProgramDetailScreen({ program, included, adding, addError, onAdd, onBack }: Props) {
  const structureLabel = STRUCTURE_TYPE_LABELS[program.structure_type] ?? program.structure_type;

  // issue #202: Telegram BackButton — переиспользует существующий onBack
  // (тот же хендлер, что у "← Назад" ниже), не создаёт вторую логику
  useBackButton(onBack, [onBack]);

  return (
    <div>
      <Button mode="outline" size="s" onClick={onBack}>
        ← Назад
      </Button>
      <p className="plan-title">{program.name}</p>

      <div className="profile-card">
        <p>{program.goal}</p>
        <p className="hint">{structureLabel}</p>
      </div>

      <Button
        className="action-button"
        size="l"
        stretched
        disabled={included || adding}
        onClick={onAdd}
      >
        {included ? "В плане ✓" : adding ? "Добавляю…" : "Добавить в план"}
      </Button>
      {addError && <p className="screen-message">Не удалось добавить курс: {addError}</p>}
    </div>
  );
}
