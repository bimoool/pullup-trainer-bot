/**
 * issue #305 (V5.6): ввод недостающих входов программы «Подтягивания» перед основной тренировкой
 * (PUT …/program-inclusions/{id}/course/inputs через apiV2.putCourseInputs). Показываются только поля из списка недостающих;
 * пустое не отправляется — сервер ничего не угадывает. Ведение теста 1RM по шагам и выбор следующей
 * резины из личного списка — шов (сюда вводится результат теста / название резины).
 */
import { Button, Input, List, Section } from "@telegram-apps/telegram-ui";
import { useState } from "react";

import { putCourseInputs } from "./apiV2";
import { type BandFields, COURSE_INPUT_FIELDS, courseInputsPayload, describePendingInputs } from "./courseV5";

const EMPTY_BAND: BandFields = { bodyweight: false, name: "", colour: "", attachment: "", body_position: "" };

function BandSection(
  { title, value, onChange, allowBodyweight, testId }:
  { title: string; value: BandFields; onChange: (next: BandFields) => void; allowBodyweight: boolean; testId: string },
) {
  return (
    <Section header={title} data-testid={testId}>
      {allowBodyweight && (
        <label className="live-hint">
          <input
            type="checkbox" checked={value.bodyweight} data-testid={`${testId}-bodyweight`}
            onChange={(e) => onChange({ ...value, bodyweight: e.target.checked })}
          />{" "}Без помощи (собственный вес)
        </label>
      )}
      {!value.bodyweight && (
        <>
          <Input
            header="Резина (модель/название)" data-testid={`${testId}-name`} value={value.name}
            onChange={(e) => onChange({ ...value, name: e.target.value })}
          />
          <Input header="Цвет" value={value.colour} onChange={(e) => onChange({ ...value, colour: e.target.value })} />
          <Input header="Крепление" value={value.attachment} onChange={(e) => onChange({ ...value, attachment: e.target.value })} />
          <Input
            header="Положение (стопа / колено)" value={value.body_position}
            onChange={(e) => onChange({ ...value, body_position: e.target.value })}
          />
        </>
      )}
    </Section>
  );
}

export function CourseSetupForm(
  { initDataRaw, inclusionId, missing, onSaved }:
  { initDataRaw: string; inclusionId: number; missing: string[]; onSaved: () => void },
) {
  const [numbers, setNumbers] = useState<Record<string, string>>({});
  const [volumeBand, setVolumeBand] = useState<BandFields>(EMPTY_BAND);
  const [strengthBand, setStrengthBand] = useState<BandFields>(EMPTY_BAND);
  const [recovery, setRecovery] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fields = missing.flatMap((item) => COURSE_INPUT_FIELDS[item] ?? []);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const body = courseInputsPayload(
        numbers,
        {
          volume: missing.includes("volume_assistance") ? volumeBand : undefined,
          strength: missing.includes("strength_assistance") ? strengthBand : undefined,
        },
        recovery,
      );
      const result = await putCourseInputs(initDataRaw, inclusionId, body);
      if (result.pending_inputs.length > 0) {
        setError(`Ещё не хватает: ${describePendingInputs(result.pending_inputs)}.`);
      }
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <List data-testid="course-setup-form">
      {fields.length > 0 && (
        <Section header="Данные для расчёта программы">
          {fields.map((field) => (
            <Input
              key={field.key} header={field.unit ? `${field.label}, ${field.unit}` : field.label} inputMode="decimal"
              data-testid={`course-input-${field.key}`} value={numbers[field.key] ?? ""}
              onChange={(e) => setNumbers({ ...numbers, [field.key]: e.target.value })}
            />
          ))}
        </Section>
      )}
      {missing.includes("volume_assistance") && (
        <BandSection title="Объёмная резина" value={volumeBand} onChange={setVolumeBand} allowBodyweight={false} testId="course-volume-band" />
      )}
      {missing.includes("strength_assistance") && (
        <BandSection title="Помощь в силовом блоке" value={strengthBand} onChange={setStrengthBand} allowBodyweight testId="course-strength-band" />
      )}
      {missing.includes("recovery_check") && (
        <Section header="Два занятия подряд хуже по обоим блокам">
          <label className="live-hint">
            <input type="checkbox" checked={recovery} onChange={(e) => setRecovery(e.target.checked)} />{" "}
            Восстановление и внешняя тяговая нагрузка проверены
          </label>
        </Section>
      )}
      {missing.includes("assistance_selection") && (
        <p className="screen-message">Выберите следующую резину в «Мои резины» (порядок определяет ступень).</p>
      )}
      {error !== null && <p className="live-hint" role="alert">{error}</p>}
      <div className="pre-transport">
        <Button className="action-button vs-primary" size="l" stretched disabled={saving} onClick={() => void save()} data-testid="course-setup-save">
          Сохранить
        </Button>
      </div>
    </List>
  );
}
