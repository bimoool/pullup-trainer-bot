import { Button, Input } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { deleteBandItem, fetchBandItems, updateBandItem, type BandItemInfo } from "./api";

type Props = { initDataRaw: string; onBack: () => void };

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; items: BandItemInfo[] };

/** Управление личным списком резин (issue #148) — переименование/удаление,
 * недостающая половина того, что issue #124 (PR 3) завело только для
 * создания/просмотра (GET/POST /api/equipment/band-items). Открывается из
 * "Профиля" (ProfileScreen.tsx), тот же приём swap'а поверх вкладки, что
 * AchievementsScreen/ProfileEditForm — не отдельная вкладка нижнего меню
 * ради одного редко используемого экрана.
 *
 * Удаление разрешено даже для резины, которая сейчас унаследована как
 * активный снаряд блока — обоснование см. в app/web/routes.py::
 * delete_band_item: blocks/elective_workouts хранят собственный снапшот
 * названия (equipment_item_name) и переживают удаление (ON DELETE SET
 * NULL), а WorkoutScreen.tsx требует явный выбор/заведение новой резины,
 * когда наследовать нечего — тем же полем, что уже показывает первую
 * тренировку на резине. */
export function BandItemsScreen({ initDataRaw, onBack }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [savedId, setSavedId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchBandItems(initDataRaw)
      .then(({ items }) => {
        if (cancelled) {
          return;
        }
        setState({ phase: "ready", items });
        setDrafts(Object.fromEntries(items.map((item) => [item.id, item.name])));
      })
      .catch((err) => {
        if (!cancelled) {
          setState({ phase: "error", message: err instanceof Error ? err.message : String(err) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  async function handleSave(item: BandItemInfo) {
    const draft = (drafts[item.id] ?? "").trim();
    if (!draft || draft === item.name) {
      return;
    }
    setError(null);
    setSavingId(item.id);
    try {
      const updated = await updateBandItem(initDataRaw, item.id, { name: draft });
      setState((prev) =>
        prev.phase === "ready"
          ? { phase: "ready", items: prev.items.map((existing) => (existing.id === updated.id ? updated : existing)) }
          : prev,
      );
      setDrafts((prev) => ({ ...prev, [updated.id]: updated.name }));
      setSavedId(item.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingId(null);
    }
  }

  async function handleDelete(item: BandItemInfo) {
    if (!window.confirm(`Удалить резину «${item.name}»? Записи о прошлых тренировках сохранят её название.`)) {
      return;
    }
    setError(null);
    setDeletingId(item.id);
    try {
      await deleteBandItem(initDataRaw, item.id);
      setState((prev) =>
        prev.phase === "ready" ? { phase: "ready", items: prev.items.filter((existing) => existing.id !== item.id) } : prev,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingId(null);
    }
  }

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю резины…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить список: {state.message}</p>;
  }

  return (
    <div>
      <p className="plan-title">Мои резины</p>

      {error && <p className="error-banner">{error}</p>}

      {state.items.length === 0 ? (
        <p className="screen-message">Пока нет ни одной сохранённой резины.</p>
      ) : (
        <div className="history-list">
          {state.items.map((item) => {
            const draft = drafts[item.id] ?? "";
            const trimmed = draft.trim();
            return (
              <div className="history-card" key={item.id}>
                <Input
                  header="Название"
                  aria-label={`Резина «${item.name}», название`}
                  value={draft}
                  onChange={(e) => {
                    setSavedId(null);
                    setDrafts((prev) => ({ ...prev, [item.id]: e.target.value }));
                  }}
                />
                {item.resistance_kg !== null && <p className="hint">{`Сопротивление: ${item.resistance_kg} кг`}</p>}
                <div className="band-create-actions">
                  <Button
                    mode="filled"
                    size="s"
                    disabled={savingId === item.id || !trimmed || trimmed === item.name}
                    onClick={() => void handleSave(item)}
                  >
                    {savingId === item.id ? "Сохраняю…" : savedId === item.id ? "✓ Сохранено" : "Сохранить"}
                  </Button>
                  <Button
                    mode="outline"
                    size="s"
                    disabled={deletingId === item.id}
                    onClick={() => void handleDelete(item)}
                  >
                    {deletingId === item.id ? "Удаляю…" : "Удалить"}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Button mode="outline" size="m" stretched onClick={onBack}>
        ← Назад
      </Button>
    </div>
  );
}
