import { Button, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchCollection, type CollectionDetailV2 } from "./apiV2";
import { collectionItemKindLabel, formatCollectionCount } from "./collectionsFormat";
import { useBackButton } from "./useBackButton";

type Props = {
  initDataRaw: string;
  collectionId: number;
  onBack: () => void;
  /** Тап по программе — существующий Program Detail (его держит HomeScreen). */
  onOpenProgram: (programId: number) => void;
  /** Тап по упражнению — существующий экран «Добавить в план» для упражнения. */
  onOpenExercise: (exerciseId: number, exerciseName: string) => void;
};

type State =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; collection: CollectionDetailV2 };

/**
 * Экран подборки (CRIMPD #271, D1 «playlist detail»): шапка (название, автор,
 * состав, описание) и список элементов; каждый элемент открывает свой существующий
 * экран, «Назад» возвращает на Главную. Подборка недоступна (404) / сбой — понятное
 * сообщение и «Назад», тупика нет.
 */
export function CollectionScreen({ initDataRaw, collectionId, onBack, onOpenProgram, onOpenExercise }: Props) {
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading" });
    fetchCollection(initDataRaw, collectionId)
      .then((collection) => !cancelled && setState({ phase: "ready", collection }))
      .catch((error) => {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, collectionId]);

  useBackButton(onBack, [onBack]);

  return (
    <div data-testid="collection-screen">
      <Button mode="outline" size="s" onClick={onBack}>
        ← Назад
      </Button>
      {state.phase === "loading" && <p className="screen-message">Загружаю подборку…</p>}
      {state.phase === "error" && (
        <p className="screen-message" data-testid="collection-error">Подборка недоступна: {state.message}</p>
      )}
      {state.phase === "ready" && (
        <>
          <div className="profile-card collection-hero" data-testid="collection-hero">
            <p className="hint" data-testid="collection-author">{state.collection.author}</p>
            <p className="plan-title" data-testid="collection-title">{state.collection.title}</p>
            <p className="hint" data-testid="collection-count">{formatCollectionCount(state.collection)}</p>
            {state.collection.description && <p data-testid="collection-description">{state.collection.description}</p>}
          </div>
          <ul className="collection-item-list" data-testid="collection-items">
            {state.collection.items.map((item) => (
              <li key={`${item.item_type}-${item.target_id}`}>
                <Section className="block-section">
                  <button
                    type="button"
                    className="collection-card-button"
                    data-testid="collection-item"
                    onClick={() => (item.item_type === "program"
                      ? onOpenProgram(item.target_id)
                      : onOpenExercise(item.target_id, item.title))}
                  >
                    <p className="hint">{collectionItemKindLabel(item.item_type)}</p>
                    <p className="block-subtitle">{item.title}</p>
                    {item.subtitle && <p className="collection-text">{item.subtitle}</p>}
                  </button>
                </Section>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
