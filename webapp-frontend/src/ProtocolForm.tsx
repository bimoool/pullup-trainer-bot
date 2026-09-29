import { useState } from "react";

import { StepperRow, TimeRow } from "./BuilderFields";
import {
  buildProtocol, draftFromProtocol, PROTOCOL_KINDS, previewLines, type ProtocolDraft, type ProtocolFormValue,
} from "./protocolConfig";

export type { ProtocolFormValue } from "./protocolConfig";
export { summarizeProtocol } from "./protocolConfig";

type Props = {
  initialExerciseName: string;
  initialProtocol: ProtocolFormValue | null;
  onCancel: () => void;
  onSubmit: (protocol: ProtocolFormValue) => void;
  submitLabel: string;
};

/**
 * UX-1 — «Как выполнять упражнение»: 1) какое упражнение, 2) тип работы (карточки с
 * объяснением, не однословные табы), 3) явно подписанные параметры, 4) превью «Так
 * будет в тренировке», 5) главная кнопка. Все значения хранятся в одном draft
 * (protocolConfig.ts) — при смене типа введённое не теряется; превью и protocol для
 * backend строятся из этого же draft. Backend-контракт не менялся.
 */
export function ProtocolForm({ initialExerciseName, initialProtocol, onCancel, onSubmit, submitLabel }: Props) {
  const [draft, setDraft] = useState<ProtocolDraft>(() => draftFromProtocol(initialProtocol));
  const patch = (changes: Partial<ProtocolDraft>) => setDraft((current) => ({ ...current, ...changes }));

  const built = buildProtocol(draft);
  const [previewMain, previewDetail] = previewLines(draft);

  function handleSubmit() {
    if (built.ok) {
      onSubmit(built.protocol);
    }
  }

  return (
    <div className="ux-form">
      <p className="ux-eyebrow">Упражнение</p>
      <h2 className="ux-exercise-name">{initialExerciseName}</h2>

      <p className="ux-section-label">Тип работы</p>
      <div className="ux-kind-list" role="radiogroup" aria-label="Тип работы">
        {PROTOCOL_KINDS.map((option) => (
          <button
            key={option.kind}
            type="button"
            role="radio"
            aria-checked={draft.kind === option.kind}
            className={`ux-kind${draft.kind === option.kind ? " ux-kind-selected" : ""}`}
            onClick={() => {
              patch({ kind: option.kind });
            }}
          >
            <span className="ux-kind-title">{option.title}</span>
            <span className="ux-kind-desc">{option.description}</span>
          </button>
        ))}
      </div>

      <p className="ux-section-label">Параметры</p>
      <div className="ux-card" data-testid="protocol-fields">
        {draft.kind === "reps_sets" && (
          <>
            <StepperRow label="Подходы" hint="Сколько раз повторить" value={draft.sets} onChange={(sets) => patch({ sets })} />
            <StepperRow label="Повторения в подходе" hint="Одинаково в каждом подходе" value={draft.reps} onChange={(reps) => patch({ reps })} />
            <TimeRow label="Отдых между подходами" seconds={draft.restSeconds} step={15} onChange={(restSeconds) => patch({ restSeconds })} />
          </>
        )}
        {draft.kind === "time_sets" && (
          <>
            <StepperRow label="Подходы" hint="Сколько раз повторить" value={draft.sets} onChange={(sets) => patch({ sets })} />
            <TimeRow label="Время подхода" hint="Сколько длится один подход" seconds={draft.durationSeconds} min={1} onChange={(durationSeconds) => patch({ durationSeconds })} />
            <TimeRow label="Отдых между подходами" seconds={draft.restSeconds} step={15} onChange={(restSeconds) => patch({ restSeconds })} />
          </>
        )}
        {draft.kind === "max_effort" && (
          <>
            <StepperRow label="Количество попыток" hint="В каждой — максимум, цели нет" value={draft.attempts} onChange={(attempts) => patch({ attempts })} />
            <TimeRow label="Отдых между попытками" seconds={draft.maxRestSeconds} step={15} onChange={(maxRestSeconds) => patch({ maxRestSeconds })} />
          </>
        )}
        {draft.kind === "interval" && (
          <>
            <TimeRow label="Работа" hint="Длина рабочего интервала" seconds={draft.workSeconds} min={1} onChange={(workSeconds) => patch({ workSeconds })} />
            <TimeRow label="Отдых" hint="Пауза после работы" seconds={draft.intervalRestSeconds} onChange={(intervalRestSeconds) => patch({ intervalRestSeconds })} />
            <TimeRow label="Общее время" hint="Раунды считаются по нему" seconds={draft.totalSeconds} step={15} min={1} onChange={(totalSeconds) => patch({ totalSeconds })} />
            <div className="ux-row ux-row-stack">
              <div className="ux-row-label">
                <span className="ux-row-title">Начать с</span>
              </div>
              <div className="ux-choice" role="radiogroup" aria-label="Начать с">
                {(["work", "rest"] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    role="radio"
                    aria-checked={draft.startsWith === option}
                    className={`ux-choice-item${draft.startsWith === option ? " ux-choice-selected" : ""}`}
                    onClick={() => patch({ startsWith: option })}
                  >
                    {option === "work" ? "Работы" : "Отдыха"}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      <div className="ux-preview" data-testid="protocol-preview" aria-live="polite">
        <span className="ux-preview-label">Так будет в тренировке</span>
        {built.ok ? (
          <>
            <span className="ux-preview-main">{previewMain}</span>
            <span className="ux-preview-detail">{previewDetail}</span>
          </>
        ) : (
          <span className="ux-preview-detail">Заполните все поля, чтобы увидеть итог</span>
        )}
      </div>

      {!built.ok && <p className="ux-error" role="alert">{built.error}</p>}

      <button type="button" className="ux-primary" disabled={!built.ok} onClick={handleSubmit}>{submitLabel}</button>
      <button type="button" className="ux-link-button" onClick={onCancel}>Отмена</button>
    </div>
  );
}
