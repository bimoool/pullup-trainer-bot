import { Button } from "@telegram-apps/telegram-ui";

import { useEffect, useState } from "react";

import { fetchProgramSchedule, type ProgramResponseV2, type ProgramScheduleV2 } from "./apiV2";
import { FavoriteHeart } from "./FavoriteHeart";
import { DAY_NAMES_RU, groupScheduleByPhase, PHASE_LABELS_RU } from "./plansOverview";
import { useBackButton } from "./useBackButton";

type Props = {
  initDataRaw: string;
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
export function ProgramDetailScreen({ initDataRaw, program, included, adding, addError, onAdd, onBack }: Props) {
  const structureLabel = STRUCTURE_TYPE_LABELS[program.structure_type] ?? program.structure_type;

  // issue #266: превью структуры из реальных ProgramItem; сбой/пусто — только описание.
  const [schedule, setSchedule] = useState<ProgramScheduleV2 | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchProgramSchedule(initDataRaw, program.id)
      .then((data) => {
        if (!cancelled) {
          setSchedule(data);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, program.id]);

  // issue #202: Telegram BackButton — переиспользует существующий onBack
  // (тот же хендлер, что у "← Назад" ниже), не создаёт вторую логику
  useBackButton(onBack, [onBack]);

  return (
    <div>
      <Button className="vs-back" mode="outline" size="s" onClick={onBack}>
        ← Назад
      </Button>
      <div className="favorite-title-row">
        <p className="plan-title" data-testid="program-detail-title">{program.name}</p>
        <FavoriteHeart initDataRaw={initDataRaw} targetType="program" targetId={program.id} />
      </div>

      <div className="profile-card">
        <p>{program.goal}</p>
        <p className="hint">{structureLabel}</p>
      </div>

      {schedule !== null && schedule.items.length > 0 && (
        <div className="profile-card" data-testid="program-schedule">
          <p className="block-subtitle">
            {schedule.duration_weeks ? `Расписание · ${schedule.duration_weeks} нед.` : "Расписание недели"}
          </p>
          {groupScheduleByPhase(schedule.items).map(([phase, rows]) => (
            <div key={phase} className="plan-week-day-group" data-testid="program-schedule-phase">
              <span className="plan-week-chip" data-testid="program-schedule-phase-chip">
                {PHASE_LABELS_RU[phase] ?? phase}
              </span>
              {rows.map((row, index) => (
                <p key={index} className="plan-item-row" data-testid="program-schedule-row">
                  {row.day_of_week !== null ? `${DAY_NAMES_RU[row.day_of_week] ?? `День ${row.day_of_week}`} · ` : ""}
                  {row.title}
                  {" — "}
                  {row.count_label}
                  {row.target_label ? ` (${row.target_label})` : ""}
                </p>
              ))}
            </div>
          ))}
        </div>
      )}

      <Button
        className="action-button vs-primary"
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
