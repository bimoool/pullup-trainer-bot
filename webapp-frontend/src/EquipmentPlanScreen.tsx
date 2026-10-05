import { Button, Section } from "@telegram-apps/telegram-ui";

import type { EquipmentInfo } from "./api";

type Props = {
  equipmentA: EquipmentInfo | null;
  equipmentB: EquipmentInfo | null;
  onContinue: () => void;
};

/** Тот же смысл, что app.bot.texts.EQUIPMENT_PLAN_ANNOUNCEMENT +
 * EQUIPMENT_STRENGTH_WEIGHT_START_HINT (app/bot/handlers/equipment.py::
 * _advance_equipment_queue/_apply_equipment_type_choice) — независимая
 * копия текста, как и весь остальной пользовательский текст Mini App.
 * bodyweight/australian явно проговаривают "снаряд не нужен" (issue #175:
 * "если снаряд не нужен — так и сказать явно, а не молчать"), не просто
 * пропускают строку. */
const EQUIPMENT_PREP_NOTE: Record<string, string> = {
  band: "Понадобится резина — выбери из уже заведённых или заведи новую на следующем экране.",
  weight:
    "Понадобится дополнительный вес (гантель, пояс с отягощением и т.п.) — для старта подойдёт вес, с которым " +
    "получается минимум 4 повторения, точное значение укажешь на следующем экране.",
  bodyweight: "Доп. снаряд не нужен — тренируешься на собственном весе.",
  australian: "Доп. снаряд не нужен — только угол корпуса, без отягощения.",
};

/** Экран выбора/подтверждения стартового снаряда (issue #175) — по образцу
 * того, как это устроено в боте (EquipmentStates, app/bot/handlers/
 * equipment.py::_begin_equipment_setup): раньше в Mini App снаряд впервые
 * упоминался мелкой строкой прямо на форме ввода результата (WorkoutScreen.tsx,
 * `plan.is_first_workout` баннер) — легко пропустить, пользователь не
 * понимал, что снаряд нужно подготовить ДО тренировки, а не во время неё.
 * Показывается один раз, до самой формы (см. WorkoutScreen.tsx) — конкретное
 * значение (вес/резина) всё ещё вводится на следующем экране, тут только
 * анонс типа снаряда по результату замера. */
export function EquipmentPlanScreen({ equipmentA, equipmentB, onContinue }: Props) {
  return (
    <div>
      <p className="plan-title">Снаряд для первой тренировки</p>
      <p className="screen-message">Исходя из твоего замера — вот план на первую тренировку:</p>

      <Section className="block-section">
        {equipmentA && (
          <>
            <p>Блок на объём — {equipmentA.label}.</p>
            <p className="hint">{EQUIPMENT_PREP_NOTE[equipmentA.type]}</p>
          </>
        )}
        {equipmentB && (
          <>
            <p>Блок на силу — {equipmentB.label}.</p>
            <p className="hint">{EQUIPMENT_PREP_NOTE[equipmentB.type]}</p>
          </>
        )}
      </Section>

      <Button className="action-button" size="l" stretched onClick={onContinue}>
        Начать тренировку
      </Button>
    </div>
  );
}
