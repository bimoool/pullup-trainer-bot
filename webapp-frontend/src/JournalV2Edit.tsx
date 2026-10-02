import { Button, Section } from "@telegram-apps/telegram-ui";
import { useRef, useState } from "react";

import { BackChevron } from "./BackChevron";
import { cloneSession, editSession, type SessionResponseV2 } from "./apiV2";
import { EFFORT_SCALE, WORKOUT_COMMENT_MAX } from "./effortScale";
import { describeJournalBlock, journalEntryTitle } from "./journalFormat";
import {
  buildEditPayload, initialDraft, isDateAllowed, SET_NOTE_MAX, todayKey, type EditDraft, type SetDraft,
} from "./journalEdit";
import { sanitizeDecimalInput } from "./decimalInput";

const UNIT_LABELS: Record<string, string> = { reps: "повт.", s: "сек", kg: "кг", deg: "°", m: "м" };

function EffortSelect({
  label, value, onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <select className="journal-edit-select" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Без оценки</option>
      {EFFORT_SCALE.map((option) => (
        <option key={option.value} value={option.value}>{option.value} {option.label}</option>
      ))}
    </select>
  );
}

/** «Изменить» запись Журнала (#262): значения, усилие и заметка подходов, усилие
 * и комментарий тренировки, дата (не в будущем). Показывается только когда
 * сервер разрешил (can_edit); 409/422 приходят текстом в баннер. */
export function JournalV2EditForm({
  initDataRaw, session, timeZone, onCancel, onSaved,
}: {
  initDataRaw: string;
  session: SessionResponseV2;
  timeZone: string;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<EditDraft>(() => initialDraft(session, timeZone));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const inFlight = useRef(false);

  function patchSet(blockIndex: number, setNumber: number, patch: Partial<SetDraft>) {
    setDraft((current) => ({
      ...current,
      sets: current.sets.map((set) =>
        set.blockIndex === blockIndex && set.setNumber === setNumber ? { ...set, ...patch } : set),
    }));
  }

  async function handleSave() {
    if (inFlight.current) {
      return;
    }
    const built = buildEditPayload(session, draft, timeZone);
    if (!built.ok) {
      setError(built.error);
      return;
    }
    inFlight.current = true;
    setSaving(true);
    setError(null);
    try {
      await editSession(initDataRaw, session.id, built.payload);
      onSaved();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
      inFlight.current = false;
      setSaving(false);
    }
  }

  return (
    <div data-testid="journal-edit-form">
      <BackChevron onClick={saving ? () => undefined : onCancel} testId="journal-edit-back" />
      <p className="plan-title">Изменить тренировку</p>
      <p className="block-subtitle">{journalEntryTitle(session)}</p>

      <span className="field-label">Дата</span>
      <input
        className="journal-edit-input"
        type="date"
        aria-label="Дата тренировки"
        value={draft.date}
        max={todayKey(timeZone)}
        onChange={(e) => setDraft({ ...draft, date: e.target.value })}
      />

      {session.blocks.map((block) => {
        const view = describeJournalBlock(block);
        const sets = draft.sets.filter((set) => set.blockIndex === block.order_index);
        if (sets.length === 0) {
          return null;
        }
        return (
          <Section key={block.order_index} className="block-section" header={view.header ?? "Упражнение"}>
            {sets.map((set) => (
              <div key={set.setNumber} className="journal-edit-set" data-testid={`edit-set-${block.order_index}-${set.setNumber}`}>
                <span className="field-label">Подход {set.setNumber}, {UNIT_LABELS[set.unit] ?? set.unit}</span>
                <input
                  className="journal-edit-input"
                  type="text"
                  inputMode="decimal"
                  aria-label={`Подход ${set.setNumber}: значение`}
                  value={set.value}
                  onChange={(e) => patchSet(set.blockIndex, set.setNumber, { value: sanitizeDecimalInput(e.target.value) })}
                />
                <EffortSelect
                  label={`Подход ${set.setNumber}: усилие`}
                  value={set.effort}
                  onChange={(value) => patchSet(set.blockIndex, set.setNumber, { effort: value })}
                />
                {/* Факультатив (#279): note — упакованные backfill-ом данные, не пользовательский текст. */}
                {session.source !== "elective" && <input
                  className="journal-edit-input"
                  type="text"
                  maxLength={SET_NOTE_MAX}
                  placeholder="Заметка к подходу"
                  aria-label={`Подход ${set.setNumber}: заметка`}
                  value={set.note}
                  onChange={(e) => patchSet(set.blockIndex, set.setNumber, { note: e.target.value })}
                />}
              </div>
            ))}
          </Section>
        );
      })}

      <span className="field-label">Как прошла тренировка?</span>
      <EffortSelect
        label="Усилие тренировки"
        value={draft.effort}
        onChange={(value) => setDraft({ ...draft, effort: value })}
      />
      <span className="field-label">Комментарий</span>
      <textarea
        className="journal-edit-input journal-edit-textarea"
        aria-label="Комментарий к тренировке"
        maxLength={WORKOUT_COMMENT_MAX}
        value={draft.comment}
        onChange={(e) => setDraft({ ...draft, comment: e.target.value })}
      />

      {error !== null && <p className="gap-banner" role="alert">{error}</p>}
      <Button className="action-button" size="l" stretched loading={saving} onClick={() => void handleSave()}>
        Сохранить
      </Button>
      <Button className="action-button" size="l" stretched mode="outline" disabled={saving} onClick={onCancel}>
        Отмена
      </Button>
    </div>
  );
}

/** «Повторить (клонировать)» (#262): дата по умолчанию — сегодня; новая запись
 * source=backdated, без влияния на прогрессию. */
export function JournalV2CloneForm({
  initDataRaw, session, timeZone, onCancel, onCloned,
}: {
  initDataRaw: string;
  session: SessionResponseV2;
  timeZone: string;
  onCancel: () => void;
  onCloned: (date: string) => void;
}) {
  const [date, setDate] = useState(() => todayKey(timeZone));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const inFlight = useRef(false);

  async function handleClone() {
    if (inFlight.current) {
      return;
    }
    if (!isDateAllowed(date, timeZone)) {
      setError("Дата не может быть в будущем.");
      return;
    }
    inFlight.current = true;
    setSaving(true);
    setError(null);
    try {
      await cloneSession(initDataRaw, session.id, date);
      onCloned(date);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
      inFlight.current = false;
      setSaving(false);
    }
  }

  return (
    <div data-testid="journal-clone-form">
      <BackChevron onClick={saving ? () => undefined : onCancel} testId="journal-clone-back" />
      <p className="plan-title">Повторить тренировку</p>
      <p className="block-subtitle">{journalEntryTitle(session)}</p>
      <p className="hint">Будет создана новая завершённая запись с теми же упражнениями и результатами.</p>
      <span className="field-label">Дата</span>
      <input
        className="journal-edit-input"
        type="date"
        aria-label="Дата новой записи"
        value={date}
        max={todayKey(timeZone)}
        onChange={(e) => setDate(e.target.value)}
      />
      {error !== null && <p className="gap-banner" role="alert">{error}</p>}
      <Button className="action-button" size="l" stretched loading={saving} onClick={() => void handleClone()}>
        Создать копию
      </Button>
      <Button className="action-button" size="l" stretched mode="outline" disabled={saving} onClick={onCancel}>
        Отмена
      </Button>
    </div>
  );
}
