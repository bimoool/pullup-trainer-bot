import { Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  addWorkoutItem,
  createWorkout,
  deleteWorkout,
  deleteWorkoutItem,
  duplicateWorkout,
  type ExerciseResponseV2,
  getWorkout,
  moveWorkoutItem,
  updateWorkout,
  updateWorkoutItem,
  type WorkoutItemResponseV2,
} from "./apiV2";
import { ExercisePickerScreen } from "./ExercisePickerScreen";
import { ProtocolForm, summarizeProtocol, type ProtocolFormValue } from "./ProtocolForm";
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
  /** Phase C5a (issue #188) — кнопка "Добавить в план" в edit-режиме
   * (не primary action — рядом с Сохранить, не вместо). Отсутствует в
   * create-режиме (workoutId ещё null, добавлять в план нечего). */
  onAddToPlan: (workoutId: number, workoutTitle: string) => void;
  /** Issue #261 — после «Удалить тренировку» (мягкое удаление на бэкенде). */
  onDeleted: () => void;
  /** Issue #261 — после «Дублировать»: caller возвращается к списку, копия уже в нём. */
  onDuplicated: (workoutId: number) => void;
};

export const DELETE_WORKOUT_CONFIRM_TEXT =
  "Удалить тренировку? Это не удалит уже выполненные тренировки из журнала.";

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
export function WorkoutEditorScreen({ initDataRaw, workoutId, onBack, onSaved, onAddToPlan, onDeleted, onDuplicated }: Props) {
  const isEditing = workoutId !== null;

  const [title, setTitle] = useState("");
  const [items, setItems] = useState<WorkoutItemResponseV2[]>([]);
  const [loading, setLoading] = useState(isEditing);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [itemActionError, setItemActionError] = useState<string | null>(null);
  const [itemView, setItemView] = useState<ItemBuilderView>({ kind: "editor" });
  const [workoutDeleteConfirm, setWorkoutDeleteConfirm] = useState(false);
  const [workoutBusy, setWorkoutBusy] = useState(false);
  const [workoutActionError, setWorkoutActionError] = useState<string | null>(null);
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

  async function handleDeleteWorkout() {
    if (workoutId === null) {
      return;
    }
    setWorkoutBusy(true);
    setWorkoutActionError(null);
    try {
      await deleteWorkout(initDataRaw, workoutId);
      onDeleted();
    } catch (error) {
      setWorkoutActionError(error instanceof Error ? error.message : String(error));
      setWorkoutBusy(false);
    }
  }

  async function handleDuplicateWorkout() {
    if (workoutId === null) {
      return;
    }
    setWorkoutBusy(true);
    setWorkoutActionError(null);
    try {
      const copy = await duplicateWorkout(initDataRaw, workoutId);
      onDuplicated(copy.id);
    } catch (error) {
      setWorkoutActionError(error instanceof Error ? error.message : String(error));
      setWorkoutBusy(false);
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

  const canSave = !saving && title.trim().length > 0;
  return (
    <div className="ux-form">
      <p className="plan-title">{isEditing ? "Редактировать тренировку" : "Новая тренировка"}</p>

      <label className="ux-field">
        <span className="ux-section-label">Название</span>
        <input
          className="ux-text-input"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Например, 3 минуты подтягиваний"
        />
      </label>

      {!isEditing && (
        <p className="ux-helper">
          Сначала название. Упражнения, подходы и отдых вы настроите на следующем шаге.
        </p>
      )}

      {isEditing && (
        <>
          <p className="ux-section-label">Упражнения{items.length > 0 ? ` · ${items.length}` : ""}</p>
          {items.length === 0 && (
            <p className="ux-helper">Пока пусто. Добавьте первое упражнение и настройте, как его выполнять.</p>
          )}
          <div className="ux-item-list" data-testid="workout-items">
            {items.map((item, index) => {
              const summary = summarizeProtocol(item.protocol);
              return (
                <div key={item.id} className="ux-item" data-testid="workout-item">
                  <button
                    type="button"
                    className="ux-item-main"
                    aria-label={`Изменить: ${item.exercise_name}`}
                    onClick={() => setItemView({ kind: "edit-item-protocol", item })}
                  >
                    <span className="ux-item-name">{item.exercise_name}</span>
                    <span className="ux-item-kind">{summary.kindTitle}</span>
                    <span className="ux-item-line">{summary.lines[0]}</span>
                    <span className="ux-item-detail">{summary.lines[1]}</span>
                    <span className="ux-item-edit" aria-hidden="true">Изменить ›</span>
                  </button>
                  <div className="ux-item-actions">
                    <button type="button" className="ux-icon-button" aria-label="Переместить выше" disabled={index === 0} onClick={() => void handleMoveItem(item.id, "up")}>↑</button>
                    <button type="button" className="ux-icon-button" aria-label="Переместить ниже" disabled={index === items.length - 1} onClick={() => void handleMoveItem(item.id, "down")}>↓</button>
                    {deleteConfirmItemId === item.id ? (
                      <>
                        <button type="button" className="ux-danger-button" onClick={() => void handleDeleteItem(item.id)}>Да, удалить</button>
                        <button type="button" className="ux-link-button ux-inline" onClick={() => setDeleteConfirmItemId(null)}>Отмена</button>
                      </>
                    ) : (
                      <button type="button" className="ux-link-button ux-inline ux-destructive" onClick={() => setDeleteConfirmItemId(item.id)}>Удалить</button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {itemActionError && <p className="gap-banner">{itemActionError}</p>}
          <button type="button" className="ux-add-button" onClick={() => setItemView({ kind: "picker" })}>
            + Добавить упражнение
          </button>
        </>
      )}

      {saveError && <p className="gap-banner">Не удалось сохранить: {saveError}</p>}

      {isEditing && workoutId !== null && (
        <div className="ux-secondary-row">
          <button type="button" className="ux-secondary" onClick={() => onAddToPlan(workoutId, title)}>
            Добавить в план
          </button>
          <button type="button" className="ux-secondary" disabled={workoutBusy} onClick={() => void handleDuplicateWorkout()}>
            Дублировать
          </button>
        </div>
      )}

      <button type="button" className="ux-primary" disabled={!canSave} onClick={() => void handleSave()}>
        {saving ? <Spinner size="s" /> : isEditing ? "Сохранить" : "Создать и добавить упражнения"}
      </button>

      {isEditing && (
        <div className="ux-delete-workout" data-testid="workout-delete">
          {workoutActionError && <p className="gap-banner">{workoutActionError}</p>}
          {workoutDeleteConfirm ? (
            <>
              <p className="ux-helper" role="alert">{DELETE_WORKOUT_CONFIRM_TEXT}</p>
              <button type="button" className="ux-danger-button" disabled={workoutBusy} onClick={() => void handleDeleteWorkout()}>
                Да, удалить
              </button>
              <button type="button" className="ux-link-button ux-inline" onClick={() => setWorkoutDeleteConfirm(false)}>
                Отмена
              </button>
            </>
          ) : (
            <button type="button" className="ux-link-button ux-destructive" onClick={() => setWorkoutDeleteConfirm(true)}>
              Удалить тренировку
            </button>
          )}
        </div>
      )}
    </div>
  );
}
