import { Section } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchCollections, type CollectionSummaryV2 } from "./apiV2";
import { formatCollectionCount } from "./collectionsFormat";

type Props = {
  initDataRaw: string;
  onOpen: (collectionId: number) => void;
};

/**
 * Ряд «Подборки» на Главной (CRIMPD #271, H5): горизонтальная карусель карточек
 * редакционных подборок (автор, название, состав, описание). Самодостаточный: сам
 * грузит список и скрывается целиком, пока подборок нет или запрос не удался —
 * сбой витрины не ломает остальную Главную.
 */
export function CollectionsRow({ initDataRaw, onOpen }: Props) {
  const [collections, setCollections] = useState<CollectionSummaryV2[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchCollections(initDataRaw)
      .then((list) => !cancelled && setCollections(list))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  if (collections.length === 0) {
    return null;
  }
  return (
    <div data-testid="collections-row">
      <p className="section-title">Подборки</p>
      <div className="home-program-row">
        {collections.map((collection) => (
          <Section key={collection.id} className="block-section home-program-card">
            <button
              type="button"
              className="collection-card-button"
              data-testid="collection-card"
              onClick={() => onOpen(collection.id)}
            >
              <p className="hint collection-author" data-testid="collection-card-author">{collection.author}</p>
              <p className="block-subtitle" data-testid="collection-card-title">{collection.title}</p>
              <p className="hint" data-testid="collection-card-count">{formatCollectionCount(collection)}</p>
              {collection.description && (
                <p className="collection-text collection-card-description">{collection.description}</p>
              )}
            </button>
          </Section>
        ))}
      </div>
    </div>
  );
}
