import { Button, Input, Section, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  addWorkoutItem,
  createWorkout,
  deleteWorkoutItem,
  type ExerciseResponseV2,
  getWorkout,
  moveWorkoutItem,
  updateWorkout,
  updateWorkoutItem,
  type WorkoutItemResponseV2,
} from "./apiV2";
import { ExercisePickerScreen } from "./ExercisePickerScreen";
import { formatProtocolSummary, ProtocolForm, type ProtocolFormValue } from "./ProtocolForm";
import { useBackButton } from "./useBackButton";

type Props = {
  initDataRaw: string;
  /** null — создание нового Workout («Новая тренировка», только поле
   * названия). number — редактирование существующего («Редактировать
   * тренировку», название + список упражнений). */
  workoutId: number | null;
  onBack: () => void;
  /** Вызывается после успешного Save с id сохранённого Workout — при
   * создании caller переключается на edit того же id (issue #188, раздел
   * 4: "после Save → переход на экран редактирования"); при
   * редактировании caller возвращается в «Мои тренировки» (раздел 5). */
  onSaved: (workoutId: number) => void;
};

/** Phase C4b-1 (issue #188) — sub-view Item Builder'а внутри edit-режима,
 * тот же локальный screen-state pattern, что весь Builder уже использует
 * (DashboardScreen.tsx::myWorkoutsView), не глобальный App navigation. */
type ItemBuilderView =
  | { kind: "editor" }
  | { kind: "picker" }
  | { kind: "new-item-protocol"; exercise: ExerciseResponseV2 }
  | { kind: "edit-item-protocol"; item: WorkoutItemResponseV2 };

/**
 * Phase C4a/C4b-1 (issue #188) — единый shell для create/edit Workout.
 * Create: только название. Edit: название + полный item builder (список,
 * добавление через Exercise Picker + Protocol Form, редактирование,
 * удаление, move ↑/↓) поверх уже готового C3 API.
 */
export function WorkoutEditorScreen({ initDataRaw, workoutId, onBack, onSaved }: Props) {
  const isEditing = workoutId !== null;

  const [title, setTitle] = useState("");
  const [items, setItems] = useState<WorkoutItemResponseV2[]>([]);
  const [loading, setLoading] = useState(isEditing);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [itemActionError, setItemActionError] = useState<string | null>(null);
  const [itemView, setItemView] = useState<ItemBuilderView>({ kind: "editor" });
  const [deleteConfirmItemId, setDeleteConfirmItemId] = useState<number | null>(null);

  useEffect(() => {
    if (workoutId === null) {
      return;
    }
    let cancelled = false;
    getWorkout(initDataRaw, workoutId)
      .then((workout) => {
        if (!cancelled) {
          setTitle(workout.title);
          setItems(workout.items ?? []);
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

  // BackButton внутри item builder sub-view должен вести назад в
  // editor, не сразу наружу (issue #188, раздел 14 — "обратно в Workout
  // Editor"), поэтому переопределяем обработчик в зависимости от
  // itemView, а не просто вызываем onBack всегда.
  useBackButton(
    () => {
      if (itemView.kind !== "editor") {
        setItemView({ kind: "editor" });
      } else {
        onBack();
      }
    },
    [itemView, onBack],
  );

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

  async function handleAddItem(exercise: ExerciseResponseV2, protocol: ProtocolFormValue) {
    if (workoutId === null) {
      return;
    }
    setItemActionError(null);
    try {
      const created = await addWorkoutItem(initDataRaw, workoutId, exercise.id, protocol);
      setItems((current) => [...current, created]);
      setItemView({ kind: "editor" });
    } catch (error) {
      setItemActionError(error instanceof Error ? error.message : String(error));
    }
  }

  async function handleUpdateItem(item: WorkoutItemResponseV2, protocol: ProtocolFormValue) {
    if (workoutId === null) {
      return;
    }
    setItemActionError(null);
    try {
      const updated = await updateWorkoutItem(initDataRaw, workoutId, item.id, { protocol });
      setItems((current) => current.map((existing) => (existing.id === updated.id ? updated : existing)));
      setItemView({ kind: "editor" });
    } catch (error) {
      setItemActionError(error instanceof Error ? error.message : String(error));
    }
  }

  async function handleDeleteItem(itemId: number) {
    if (workoutId === null) {
      return;
    }
    setItemActionError(null);
    try {
      await deleteWorkoutItem(initDataRaw, workoutId, itemId);
      setItems((current) => current.filter((item) => item.id !== itemId));
      setDeleteConfirmItemId(null);
    } catch (error) {
      setItemActionError(error instanceof Error ? error.message : String(error));
    }
  }

  async function handleMoveItem(itemId: number, direction: "up" | "down") {
    if (workoutId === null) {
      return;
    }
    setItemActionError(null);
    try {
      const updated = await moveWorkoutItem(initDataRaw, workoutId, itemId, direction);
      setItems(updated.items ?? []);
    } catch (error) {
      setItemActionError(error instanceof Error ? error.message : String(error));
    }
  }

  if (loading) {
    return <Spinner size="m" />;
  }
  if (loadError) {
    return <p className="gap-banner">Не удалось загрузить: {loadError}</p>;
  }

  if (itemView.kind === "picker") {
    return (
      <ExercisePickerScreen
        initDataRaw={initDataRaw}
        onBack={() => setItemView({ kind: "editor" })}
        onSelect={(exercise) => setItemView({ kind: "new-item-protocol", exercise })}
      />
    );
  }

  if (itemView.kind === "new-item-protocol") {
    return (
      <ProtocolForm
        initialExerciseName={itemView.exercise.name}
        initialProtocol={null}
        submitLabel="Добавить"
        onCancel={() => setItemView({ kind: "editor" })}
        onSubmit={(protocol) => void handleAddItem(itemView.exercise, protocol)}
      />
    );
  }

  if (itemView.kind === "edit-item-protocol") {
    return (
      <ProtocolForm
        initialExerciseName={itemView.item.exercise_name}
        initialProtocol={itemView.item.protocol}
        submitLabel="Сохранить"
        onCancel={() => setItemView({ kind: "editor" })}
        onSubmit={(protocol) => void handleUpdateItem(itemView.item, protocol)}
      />
    );
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
          {items.length === 0 && <p className="screen-message">Пока не добавлены</p>}
          {items.map((item, index) => (
            <div key={item.id} className="plan-week-day-group">
              <p className="plan-item-row">{item.exercise_name}</p>
              <p className="block-subtitle">{formatProtocolSummary(item.protocol)}</p>
              <Button size="s" onClick={() => setItemView({ kind: "edit-item-protocol", item })}>
                Редактировать
              </Button>
              <Button size="s" disabled={index === 0} onClick={() => void handleMoveItem(item.id, "up")}>
                ↑
              </Button>
              <Button size="s" disabled={index === items.length - 1} onClick={() => void handleMoveItem(item.id, "down")}>
                ↓
              </Button>
              {deleteConfirmItemId === item.id ? (
                <>
                  <Button size="s" mode="outline" onClick={() => void handleDeleteItem(item.id)}>
                    Подтвердить удаление
                  </Button>
                  <Button size="s" mode="outline" onClick={() => setDeleteConfirmItemId(null)}>
                    Отмена
                  </Button>
                </>
              ) : (
                <Button size="s" mode="outline" onClick={() => setDeleteConfirmItemId(item.id)}>
                  Удалить
                </Button>
              )}
            </div>
          ))}
          {itemActionError && <p className="gap-banner">{itemActionError}</p>}
          <Button className="action-button" size="m" stretched onClick={() => setItemView({ kind: "picker" })}>
            Добавить упражнение
          </Button>
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
