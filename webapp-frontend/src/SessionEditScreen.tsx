import { Button, Input, Section } from "@telegram-apps/telegram-ui";
import { useState } from "react";

import {
  applyProgressionCascade,
  previewProgressionCascade,
  type PlanItemDeltaResponse,
  type ProgramInclusionResponseV2,
  type SessionResponseV2,
  type SetLogInputV2,
} from "./apiV2";

type Props = {
  initDataRaw: string;
  session: SessionResponseV2;
  inclusion: ProgramInclusionResponseV2;
  onDone: () => void;
};

type EditableSet = SetLogInputV2 & { key: string };

function editableSetsForRole(session: SessionResponseV2, exerciseId: number): EditableSet[] {
  const block = session.blocks.find((b) => b.exercise_id === exerciseId);
  if (block === undefined) {
    return [];
  }
  return block.set_logs.map((log) => ({
    key: `${exerciseId}-${log.set_number}`,
    set_number: log.set_number,
    metric_type: log.metric_type as SetLogInputV2["metric_type"],
    value: log.value,
    unit: log.unit,
    is_max_set: log.is_max_set,
    effort: log.effort,
    note: log.note,
  }));
}

function roleExerciseId(inclusion: ProgramInclusionResponseV2, role: string): number | null {
  return inclusion.snapshot.exercises?.find((e) => e.role === role)?.exercise_id ?? null;
}

/**
 * Правка исторической v2-сессии + preview/apply каскада прогрессии (issue
 * #185, раздел 10.6/15 — E2E "Правка вчерашней сессии → лист preview с
 * изменениями → Применить → target следующей сессии изменился; Оставить →
 * не изменился"). preview НЕ имеет побочных эффектов (см. тест
 * test_v2_progression_cascade.py::test_preview_and_apply_cascade...) — кнопка
 * "Оставить" поэтому просто закрывает экран без отдельного запроса отмены.
 */
export function SessionEditScreen({ initDataRaw, session, inclusion, onDone }: Props) {
  const blockAExerciseId = roleExerciseId(inclusion, "block_a");
  const blockBExerciseId = roleExerciseId(inclusion, "block_b");
  const [blockA, setBlockA] = useState<EditableSet[]>(
    blockAExerciseId !== null ? editableSetsForRole(session, blockAExerciseId) : [],
  );
  const [blockB, setBlockB] = useState<EditableSet[]>(
    blockBExerciseId !== null ? editableSetsForRole(session, blockBExerciseId) : [],
  );
  const [deltas, setDeltas] = useState<PlanItemDeltaResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function updateValue(list: EditableSet[], setList: (v: EditableSet[]) => void, key: string, value: string) {
    setList(list.map((set) => (set.key === key ? { ...set, value } : set)));
    setDeltas(null);
  }

  function stripKeys(list: EditableSet[]): SetLogInputV2[] {
    return list.map(({ key: _key, ...rest }) => rest);
  }

  async function handlePreview() {
    setBusy(true);
    setError(null);
    try {
      const response = await previewProgressionCascade(
        initDataRaw, inclusion.id, session.id,
        blockA.length > 0 ? stripKeys(blockA) : undefined,
        blockB.length > 0 ? stripKeys(blockB) : undefined,
      );
      setDeltas(response.deltas);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleApply() {
    setBusy(true);
    setError(null);
    try {
      await applyProgressionCascade(
        initDataRaw, inclusion.id, session.id,
        blockA.length > 0 ? stripKeys(blockA) : undefined,
        blockB.length > 0 ? stripKeys(blockB) : undefined,
      );
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  function renderBlock(letter: "A" | "Б", sets: EditableSet[], setList: (v: EditableSet[]) => void) {
    if (sets.length === 0) {
      return null;
    }
    return (
      <Section className="block-section" header={`Блок ${letter}`}>
        {sets.map((set) => {
          // "Блок A/Б, подход N" — та же конвенция подписи, что
          // WorkoutScreen.tsx (см. ready.spec.ts): без префикса блока
          // "подход 1" у блока A и блока Б совпали бы дословно, getByLabel в
          // E2E не смог бы различить. aria-label дублирует header намеренно
          // — telegram-ui's Input не делает header accessible name инпута
          // (см. комментарий в SessionLiveScreen.tsx), везде в проекте для
          // этого используется явный aria-label, не header.
          const label = set.is_max_set ? `Блок ${letter}, подход на максимум` : `Блок ${letter}, подход ${set.set_number}`;
          return (
            <Input
              key={set.key}
              header={label}
              aria-label={label}
              type="number"
              inputMode="decimal"
              value={set.value}
              onChange={(e) => updateValue(sets, setList, set.key, e.target.value)}
            />
          );
        })}
      </Section>
    );
  }

  return (
    <div>
      <p className="plan-title">Правка сессии от {new Date(session.performed_at).toLocaleDateString()}</p>

      {renderBlock("A", blockA, setBlockA)}
      {renderBlock("Б", blockB, setBlockB)}

      {error !== null && <p className="screen-message">{error}</p>}

      {deltas === null && (
        <Button className="action-button" size="l" stretched disabled={busy} onClick={() => void handlePreview()}>
          Предпросмотр
        </Button>
      )}

      {deltas !== null && (
        <>
          <Section className="block-section" header="Изменится план">
            {deltas.length === 0 && <p className="block-subtitle">Без изменений — цель не сдвинулась.</p>}
            {deltas.map((delta) => (
              <p key={delta.plan_item_id ?? delta.exercise} className="block-subtitle">
                {delta.exercise}: {delta.before} → {delta.after}
              </p>
            ))}
          </Section>
          <Button className="action-button" size="l" stretched disabled={busy} onClick={() => void handleApply()}>
            Применить
          </Button>
          <Button className="action-button" size="l" stretched mode="outline" disabled={busy} onClick={onDone}>
            Оставить
          </Button>
        </>
      )}
    </div>
  );
}
