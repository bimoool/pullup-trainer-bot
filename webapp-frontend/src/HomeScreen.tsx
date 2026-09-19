import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchDashboard, type DashboardResponse } from "./api";
import { createProgramInclusion, fetchPlan, fetchPrograms, type ProgramResponse } from "./apiV2";
import { streakValue } from "./DashboardScreen";

type Props = {
  initDataRaw: string;
  /** Открывает вкладку "Тренировка" (не пункт нижнего меню — issue #183,
   * волна 5b, см. App.tsx). WorkoutScreen сам показывает нужное состояние
   * (форма, "не готов", бэкдейт и т.п.) — Главная не дублирует эту логику. */
  onOpenWorkout: () => void;
  /** Открывает вкладку "Планы" — туда переехал прежний Dashboard (issue #175,
   * волна 4) целиком, со сводкой недели и статусом готовности; с issue #188
   * (волна 6) там же видны подключённые курсы. */
  onOpenPlans: () => void;
};

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | {
      phase: "ready";
      dashboard: DashboardResponse;
      programs: ProgramResponse[];
      includedProgramIds: Set<number>;
    };

type CatalogView = { mode: "list" } | { mode: "card"; program: ProgramResponse };

/**
 * Стартовый экран Mini App (issue #183, волна 5b; référence — crimpd-reference
 * skill, "Пять вкладок... Главная-каталог"). Каталог (issue #188, волна 6) —
 * реальный список из GET /api/v2/programs вместо честной заглушки волны 5b;
 * сейчас там ровно один курс («Подтягивания», seed из scripts/backfill_multi_
 * program.py) — второй курс не предоставлен владельцем продукта (план,
 * раздел 16), архитектура каталога/карточки не завязана на число курсов.
 * Полная сводка (сколько тренировок, статус готовности, кнопка "Начать
 * тренировку") осталась на "Планах" (DashboardScreen.tsx) как есть — здесь
 * только компактный виджет недели.
 */
export function HomeScreen({ initDataRaw, onOpenWorkout, onOpenPlans }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [catalogView, setCatalogView] = useState<CatalogView>({ mode: "list" });
  const [addingProgramId, setAddingProgramId] = useState<number | null>(null);
  const [addError, setAddError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchDashboard(initDataRaw), fetchPrograms(initDataRaw), fetchPlan(initDataRaw)])
      .then(([dashboard, programs, plan]) => {
        if (!cancelled) {
          const includedProgramIds = new Set(
            (plan?.program_inclusions ?? []).map((inclusion) => inclusion.program_id),
          );
          setState({ phase: "ready", dashboard, programs, includedProgramIds });
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

  /** «Добавить в план» (раздел 10.3). Диалог пересечений (10.5) — вне охвата
   * этого чекпоинта: единственный сеяный курс не может пересечься сам с
   * собой, второго курса для проверки нет (план, раздел 16). */
  async function handleAddToPlan(program: ProgramResponse) {
    setAddError(null);
    setAddingProgramId(program.id);
    try {
      await createProgramInclusion(initDataRaw, program.id);
      setState((previous) =>
        previous.phase === "ready"
          ? { ...previous, includedProgramIds: new Set(previous.includedProgramIds).add(program.id) }
          : previous,
      );
    } catch (error) {
      setAddError(error instanceof Error ? error.message : String(error));
    } finally {
      setAddingProgramId(null);
    }
  }

  if (state.phase === "ready" && catalogView.mode === "card") {
    return (
      <ProgramCardView
        program={catalogView.program}
        isIncluded={state.includedProgramIds.has(catalogView.program.id)}
        isAdding={addingProgramId === catalogView.program.id}
        error={addError}
        onAdd={() => void handleAddToPlan(catalogView.program)}
        onOpenPlans={onOpenPlans}
        onBack={() => setCatalogView({ mode: "list" })}
      />
    );
  }

  return (
    <div>
      <p className="plan-title">Главная</p>

      {state.phase === "loading" && <p className="screen-message">Загружаю…</p>}
      {state.phase === "error" && <p className="screen-message">Не удалось загрузить: {state.message}</p>}
      {state.phase === "ready" && (
        <>
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

          <Button className="action-button" size="l" stretched onClick={onOpenPlans}>
            К плану
          </Button>

          <Button className="action-button" size="l" stretched mode="outline" onClick={onOpenWorkout}>
            Тренировка
          </Button>

          <p className="section-title">Курсы</p>
          {state.programs.length === 0 && <p className="screen-message">Каталог пока пуст.</p>}
          {state.programs.length > 0 && (
            <div className="catalog-list">
              {state.programs.map((program) => (
                <button
                  key={program.id}
                  type="button"
                  className="catalog-card"
                  onClick={() => setCatalogView({ mode: "card", program })}
                >
                  <p className="catalog-card-title">{program.name}</p>
                  <p className="hint">{state.includedProgramIds.has(program.id) ? "В плане ✓" : program.goal}</p>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

type ProgramCardViewProps = {
  program: ProgramResponse;
  isIncluded: boolean;
  isAdding: boolean;
  error: string | null;
  onAdd: () => void;
  onOpenPlans: () => void;
  onBack: () => void;
};

/**
 * Карточка курса (раздел 10.3) — обложка/уровни/снаряжение из спеки здесь
 * нет: `ProgramResponse` (app/web/schemas_v2.py) пока не возвращает эти
 * поля — рисуем честно то, что реально отдаёт бэкенд, не подставляем
 * плейсхолдеры под несуществующие данные.
 */
function ProgramCardView({ program, isIncluded, isAdding, error, onAdd, onOpenPlans, onBack }: ProgramCardViewProps) {
  return (
    <div>
      <Button mode="outline" size="s" onClick={onBack}>
        ← Назад
      </Button>
      <p className="plan-title">{program.name}</p>

      <div className="profile-card">
        <p>{program.goal}</p>
      </div>

      {error && <p className="screen-message">Не удалось добавить в план: {error}</p>}

      {isIncluded ? (
        <>
          <Button className="action-button" size="l" stretched disabled>
            В плане ✓
          </Button>
          <Button className="action-button" size="l" stretched mode="outline" onClick={onOpenPlans}>
            Перейти в «Планы»
          </Button>
        </>
      ) : (
        <Button className="action-button" size="l" stretched onClick={onAdd} loading={isAdding}>
          Добавить в план
        </Button>
      )}
    </div>
  );
}
