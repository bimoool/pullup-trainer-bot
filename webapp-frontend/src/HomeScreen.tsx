import { Button, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchDashboard, type DashboardResponse } from "./api";
import { createProgramInclusion, fetchPlan, fetchPrograms, type ProgramResponseV2 } from "./apiV2";
import { streakValue } from "./DashboardScreen";

type Props = {
  initDataRaw: string;
  /** Открывает вкладку "Тренировка" (не пункт нижнего меню — issue #183,
   * волна 5b, см. App.tsx). WorkoutScreen сам показывает нужное состояние
   * (форма, "не готов", бэкдейт и т.п.) — Главная не дублирует эту логику. */
  onOpenWorkout: () => void;
  /** Открывает вкладку "Планы" — туда переехал прежний Dashboard (issue #175,
   * волна 4) целиком, со сводкой недели и статусом готовности. */
  onOpenPlans: () => void;
};

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; dashboard: DashboardResponse };

type CatalogState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; programs: ProgramResponseV2[]; includedProgramIds: Set<number> };

type AddState = { phase: "idle" } | { phase: "adding"; programId: number } | { phase: "error"; message: string };

/**
 * Стартовый экран Mini App (issue #183, волна 5b; référence — crimpd-reference
 * skill, "Пять вкладок... Главная-каталог"). Каталог курсов — волна 6, здесь
 * ещё нет ни одного курса, поэтому вместо заглушки, похожей на рабочий
 * каталог, — честный текст. Полная сводка (сколько тренировок, статус
 * готовности, кнопка "Начать тренировку") осталась на "Планах"
 * (DashboardScreen.tsx) как есть — здесь только компактный виджет недели.
 */
export function HomeScreen({ initDataRaw, onOpenWorkout, onOpenPlans }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [catalog, setCatalog] = useState<CatalogState>({ phase: "loading" });
  const [addState, setAddState] = useState<AddState>({ phase: "idle" });

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

  useEffect(() => {
    let cancelled = false;
    fetchDashboard(initDataRaw)
      .then((dashboard) => {
        if (!cancelled) {
          setState({ phase: "ready", dashboard });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  return (
    <div>
      <p className="plan-title">Главная</p>

      {state.phase === "loading" && <p className="screen-message">Загружаю…</p>}
      {state.phase === "error" && <p className="screen-message">Не удалось загрузить: {state.message}</p>}
      {state.phase === "ready" && (
        <div className="stat-grid">
          <div className="stat-tile">
            <div className="stat-value">{state.dashboard.workouts_count}</div>
            <div className="stat-label">Тренировок всего</div>
          </div>
          <div className="stat-tile">
            <div className="stat-value">
              {streakValue(state.dashboard.streak, state.dashboard.workouts_count)}
            </div>
            <div className="stat-label">Подряд без перерыва</div>
          </div>
        </div>
      )}

      <Button className="action-button" size="l" stretched onClick={onOpenPlans}>
        К плану
      </Button>

      <Button className="action-button" size="l" stretched mode="outline" onClick={onOpenWorkout}>
        Тренировка
      </Button>

      <p className="section-title">Курсы</p>
      {/* Capability A (issue #188) — минимальный каталог: одна карточка на
          seed-программу, без категорий/поиска/уровней (это остаток волны 6,
          не блокирует "Добавить в план"). Курс уже в плане → кнопка
          "В плане ✓" неактивна, повторно не добавляет (10.3). */}
      {catalog.phase === "loading" && <p className="screen-message">Загружаю каталог…</p>}
      {catalog.phase === "error" && <p className="screen-message">Не удалось загрузить каталог: {catalog.message}</p>}
      {catalog.phase === "ready" && catalog.programs.length === 0 && (
        <p className="screen-message">Каталог курсов появится здесь позже.</p>
      )}
      {catalog.phase === "ready" &&
        catalog.programs.map((program) => {
          const included = catalog.includedProgramIds.has(program.id);
          const adding = addState.phase === "adding" && addState.programId === program.id;
          return (
            <Section key={program.id} className="block-section">
              <p className="block-subtitle">{program.name}</p>
              <p className="screen-message">{program.goal}</p>
              <Button
                className="action-button"
                size="m"
                stretched
                disabled={included || adding}
                onClick={() => handleAddToPlan(program.id)}
              >
                {included ? "В плане ✓" : adding ? "Добавляю…" : "Добавить в план"}
              </Button>
            </Section>
          );
        })}
      {addState.phase === "error" && (
        <p className="screen-message">Не удалось добавить курс: {addState.message}</p>
      )}
    </div>
  );
}
