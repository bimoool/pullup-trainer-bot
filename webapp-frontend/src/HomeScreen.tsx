import { Section } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { createProgramInclusion, fetchPlan, fetchPrograms, type ProgramResponseV2 } from "./apiV2";
import { ProgramDetailScreen } from "./ProgramDetailScreen";

type Props = {
  initDataRaw: string;
};

type CatalogState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; programs: ProgramResponseV2[]; includedProgramIds: Set<number> };

type AddState = { phase: "idle" } | { phase: "adding"; programId: number } | { phase: "error"; message: string };

/**
 * Стартовый экран Mini App — каталог программ (issue #205, Checkpoint 5B;
 * crimpd-reference skill: "Главная = каталог программ / вход в Program Detail").
 * Home не дублирует Plans/Analytics/workout controls — только каталог, состояние
 * "В плане", переход в Program Detail. Полная сводка (статус готовности,
 * кнопка "Начать тренировку") на "Планах" (DashboardScreen.tsx).
 */
export function HomeScreen({ initDataRaw }: Props) {
  const [catalog, setCatalog] = useState<CatalogState>({ phase: "loading" });
  const [addState, setAddState] = useState<AddState>({ phase: "idle" });
  // Program Detail (issue #192) — тот же приём "swap внутри вкладки", что
  // showAchievements в ProfileScreen: id, не boolean, чтобы Detail-экран мог
  // прочитать конкретную карточку каталога.
  const [selectedProgramId, setSelectedProgramId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchPrograms(initDataRaw), fetchPlan(initDataRaw)])
      .then(([programs, plan]) => {
        if (cancelled) {
          return;
        }
        const includedProgramIds = new Set(
          (plan?.program_inclusions ?? []).filter((i) => i.is_active).map((i) => i.program_id),
        );
        setCatalog({ phase: "ready", programs, includedProgramIds });
      })
      .catch((error) => {
        if (!cancelled) {
          setCatalog({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  async function handleAddToPlan(programId: number) {
    setAddState({ phase: "adding", programId });
    try {
      await createProgramInclusion(initDataRaw, programId);
      setCatalog((prev) =>
        prev.phase === "ready"
          ? { ...prev, includedProgramIds: new Set(prev.includedProgramIds).add(programId) }
          : prev,
      );
      setAddState({ phase: "idle" });
    } catch (error) {
      setAddState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  if (selectedProgramId !== null && catalog.phase === "ready") {
    const program = catalog.programs.find((p) => p.id === selectedProgramId);
    if (program) {
      const included = catalog.includedProgramIds.has(program.id);
      const adding = addState.phase === "adding" && addState.programId === program.id;
      return (
        <ProgramDetailScreen
          program={program}
          included={included}
          adding={adding}
          addError={addState.phase === "error" ? addState.message : null}
          onAdd={() => void handleAddToPlan(program.id)}
          onBack={() => setSelectedProgramId(null)}
        />
      );
    }
  }

  return (
    <div>
      <p className="plan-title">Главная</p>

      <p className="section-title">Курсы</p>
      {/* Capability A (issue #188) — минимальный каталог: одна карточка на
          seed-программу, без категорий/поиска/уровней (это остаток волны 6).
          Issue #192 — карточка сама больше не выполняет действие, тап ведёт
          на отдельный Program Detail (ProgramDetailScreen.tsx), туда же
          переехала кнопка "Добавить в план"/"В плане ✓"; здесь остаётся
          только статус — краткий текст, не кнопка. */}
      {catalog.phase === "loading" && <p className="screen-message">Загружаю каталог…</p>}
      {catalog.phase === "error" && <p className="screen-message">Не удалось загрузить каталог: {catalog.message}</p>}
      {catalog.phase === "ready" && catalog.programs.length === 0 && (
        <p className="screen-message">Каталог курсов появится здесь позже.</p>
      )}
      {catalog.phase === "ready" &&
        catalog.programs.map((program) => {
          const included = catalog.includedProgramIds.has(program.id);
          return (
            <Section key={program.id} className="block-section">
              <button
                type="button"
                className="program-card-button"
                onClick={() => setSelectedProgramId(program.id)}
              >
                <p className="block-subtitle">{program.name}</p>
                <p className="screen-message">{program.goal}</p>
                {included && <p className="hint">✓ В плане</p>}
              </button>
            </Section>
          );
        })}
    </div>
  );
}
