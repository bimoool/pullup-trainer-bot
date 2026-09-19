import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { QueryClient } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import type { ReactNode } from "react";

/**
 * Кэш GET-ответов /api/v2/* (план, статус дашборда, журнал сессий) переживает
 * reload — см. докстринг offlineSession.ts про разделение ролей библиотек:
 * САМ офлайн-лог активной сессии (то, что обязано пережить закрытие Mini App
 * без сети) лежит в IndexedDB через idb-keyval (offlineSession.ts), не здесь;
 * localStorage тут используется по прямому назначению query-sync-storage-
 * persister — маленький, синхронный, для read-кэша, не для очереди мутаций.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

const persister = createSyncStoragePersister({
  storage: window.localStorage,
  key: "pullup-v2-query-cache",
});

export function OfflineQueryProvider({ children }: { children: ReactNode }) {
  return (
    <PersistQueryClientProvider client={queryClient} persistOptions={{ persister, maxAge: 1000 * 60 * 60 * 24 }}>
      {children}
    </PersistQueryClientProvider>
  );
}
