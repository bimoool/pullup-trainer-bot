import { Button, Input, Section, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { createWorkout, getWorkout, updateWorkout } from "./apiV2";
import { useBackButton } from "./useBackButton";

type Props = {
  initDataRaw: string;
  /** null — создание нового Workout («Новая тренировка», только поле
   * названия). number — редактирование существующего («Редактировать
   * тренировку», название + placeholder для будущих упражнений — item
   * editor явно вне scope этого chunk, C4b). */
  workoutId: number | null;
  onBack: () => void;
  /** Вызывается после успешного Save с id сохранённого Workout — при
   * создании caller переключается на edit того же id (issue #188, раздел
   * 4: "после Save → переход на экран редактирования"); при
   * редактировании caller возвращается в «Мои тренировки» (раздел 5). */
  onSaved: (workoutId: number) => void;
};

/**
 * Phase C4a (issue #188) — единый shell для create/edit, оба режима — по
 * сути одно и то же поле (название) + Save, различается только заголовок,
 * наличие placeholder-секции "Упражнения" в edit-режиме и то, куда
 * переходит caller после успешного Save (см. onSaved выше). Item editor/
 * Exercise Picker/protocol forms/reorder — явно вне scope, следующая
 * волна (C4b).
 */
export function WorkoutEditorScreen({ initDataRaw, workoutId, onBack, onSaved }: Props) {
  const isEditing = workoutId !== null;

  const [title, setTitle] = useState("");
  const [loading, setLoading] = useState(isEditing);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (workoutId === null) {
      return;
    }
    let cancelled = false;
    getWorkout(initDataRaw, workoutId)
      .then((workout) => {
        if (!cancelled) {
          setTitle(workout.title);
          setLoading(false);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setLoadError(error instanceof Error ? error.message : String(error));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, workoutId]);

  useBackButton(onBack, [onBack]);

  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    try {
      if (workoutId === null) {
        const created = await createWorkout(initDataRaw, title);
        setSaving(false);
        onSaved(created.id);
      } else {
        const updated = await updateWorkout(initDataRaw, workoutId, title);
        setSaving(false);
        onSaved(updated.id);
      }
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
      setSaving(false);
    }
  }

  if (loading) {
    return <Spinner size="m" />;
  }
  if (loadError) {
    return <p className="gap-banner">Не удалось загрузить: {loadError}</p>;
  }

  return (
    <div>
      <p className="plan-title">{isEditing ? "Редактировать тренировку" : "Новая тренировка"}</p>

      <Input
        header="Название"
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        placeholder="Например, 3 минуты подтягиваний"
      />

      {isEditing && (
        <Section className="block-section" header="Упражнения">
          <p className="screen-message">Пока не добавлены</p>
        </Section>
      )}

      {saveError && <p className="gap-banner">Не удалось сохранить: {saveError}</p>}

      <Button
        className="action-button" size="l" stretched
        disabled={saving || title.trim().length === 0}
        onClick={() => void handleSave()}
      >
        {saving ? <Spinner size="s" /> : "Сохранить"}
      </Button>
    </div>
  );
}
