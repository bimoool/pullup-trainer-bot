import { Button, Input, Placeholder, Section, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  fetchElectivePlan,
  submitElective,
  type ElectivePlan,
  type ElectiveSubmitResponse,
  type ElectiveTypeInfo,
} from "./api";
import { SetInputGrid, parseSetValue, parseSetValues, replaceAt } from "./WorkoutScreen";

type Props = {
  initDataRaw: string;
  onCancel: () => void;
  onDone: () => void;
};

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "not_ready"; status: string }
  | { phase: "picker"; plan: ElectivePlan }
  | { phase: "form"; plan: ElectivePlan; type: ElectiveTypeInfo }
  | { phase: "done"; result: ElectiveSubmitResponse };

// Тот же узкий набор статусов, что и у остальных *PlanResponse — форма не
// показывается, факультатив не за паивеллом (нет "no_access", см.
// app/web/routes.py::get_elective_plan).
const STATUS_MESSAGES: Record<string, string> = {
  not_onboarded: "Похоже, ты ещё не проходил онбординг — начни его в боте.",
  needs_first_workout: "Факультатив станет доступен после первой тренировки.",
};

/**
 * Экран факультатива Mini App (issue #94) — тот же путь, что
 * handle_electives_start/_finalize_elective бота (app/bot/handlers/electives.py):
 * ротация без повтора (plan.available_types уже отфильтрован сервером) +
 * недельный лимит (plan.elective_allowed). Открывается либо кнопкой
 * "🎯 Факультатив" в обычном плане тренировки, либо проактивно из статуса
 * "сегодня отдых" (WorkoutScreen.tsx, status === "too_early") — plan сам
 * сообщает is_rest_day, форма от этого не меняется, только текст.
 *
 * `Placeholder`/`Spinner` вместо `.screen-message` на состояниях загрузки/
 * ошибки/недоступности/исчерпанного лимита (issue #142) — тот же базовый
 * паттерн, что AchievementsScreen.tsx. Раскладка ввода подходов
 * (`SetInputGrid`, `.block-section`/`.workout-mode-buttons`) и общие
 * layout-классы (`.plan-title`/`.action-button`/`.error-banner`/
 * `.done-card`/`.gap-banner`) не тронуты — общие с ещё немигрированным
 * WorkoutScreen.tsx, чистка/замена — в финальном PR 7 по плану.
 */
export function ElectiveScreen({ initDataRaw, onCancel, onDone }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [seqValues, setSeqValues] = useState<string[]>([]);
  const [totalValue, setTotalValue] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const plan = await fetchElectivePlan(initDataRaw);
        if (cancelled) {
          return;
        }
        if (plan.status !== "ready") {
          setState({ phase: "not_ready", status: plan.status });
          return;
        }
        setState({ phase: "picker", plan });
      } catch (error) {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  function chooseType(plan: ElectivePlan, type: ElectiveTypeInfo) {
    setFormError(null);
    setTotalValue("");
    setSeqValues(Array(type.min_count ?? 1).fill(""));
    setState({ phase: "form", plan, type });
  }

  async function handleSubmit(type: ElectiveTypeInfo) {
    if (type.input_kind === "total") {
      const parsed = parseSetValue(totalValue);
      if (parsed === null || parsed <= 0) {
        setFormError("Укажи одно целое положительное число — сколько всего получилось повторений.");
        return;
      }
      setFormError(null);
      setSubmitting(true);
      try {
        const result = await submitElective(initDataRaw, {
          elective_type: type.value, reps_sequence: null, total_reps: parsed,
        });
        if (result.status !== "ok") {
          setState({ phase: "not_ready", status: result.status });
          return;
        }
        setState({ phase: "done", result });
      } catch (error) {
        setFormError(error instanceof Error ? error.message : String(error));
      } finally {
        setSubmitting(false);
      }
      return;
    }

    const parsed = parseSetValues(seqValues);
    if (parsed === null) {
      setFormError("Заполни все подходы числами — пустые или нечисловые поля недопустимы.");
      return;
    }
    setFormError(null);
    setSubmitting(true);
    try {
      const result = await submitElective(initDataRaw, {
        elective_type: type.value,
        reps_sequence: parsed,
        total_reps: parsed.reduce((sum, n) => sum + n, 0),
      });
      if (result.status !== "ok") {
        setState({ phase: "not_ready", status: result.status });
        return;
      }
      setState({ phase: "done", result });
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  }

  if (state.phase === "loading") {
    return (
      <Placeholder>
        <Spinner size="m" />
      </Placeholder>
    );
  }
  if (state.phase === "error") {
    return (
      <div>
        <Placeholder description={`Не удалось загрузить факультатив: ${state.message}`} />
        <Button className="action-button" size="l" stretched mode="outline" onClick={onCancel}>
          Назад
        </Button>
      </div>
    );
  }
  if (state.phase === "not_ready") {
    return (
      <div>
        <Placeholder
          description={STATUS_MESSAGES[state.status] ?? `Факультатив пока недоступен (статус: ${state.status}).`}
        />
        <Button className="action-button" size="l" stretched mode="outline" onClick={onCancel}>
          Назад
        </Button>
      </div>
    );
  }
  if (state.phase === "done") {
    const { result } = state;
    return (
      <div className="done-card">
        <div className="done-check">✓</div>
        <p className="done-title">Факультатив записан</p>
        <div className="done-stats">
          <p>{result.result_text}</p>
          {result.equipment_label && <p className="hint">Снаряд — {result.equipment_label}.</p>}
          <p className="hint">В план и текущий цикл это не входит — только статистика и общий объём.</p>
        </div>
        <Button className="action-button" size="l" stretched onClick={onDone}>
          Готово
        </Button>
      </div>
    );
  }

  if (state.phase === "form") {
    const { plan, type } = state;
    return (
      <div>
        <p className="plan-title">{type.label}</p>
        {plan.is_rest_day && <p className="gap-banner">Сегодня как раз день отдыха — хороший момент для этого.</p>}

        {type.input_kind === "total" ? (
          <Input
            header={
              type.volume_goal !== null
                ? `Сколько всего получилось повторений (ориентир — ${type.volume_goal})`
                : "Сколько всего получилось повторений"
            }
            type="number"
            inputMode="numeric"
            min={1}
            max={9999}
            aria-label="Итого повторений"
            value={totalValue}
            onChange={(e) => setTotalValue(e.target.value)}
          />
        ) : (
          <Section className="block-section" header="Подходы по порядку">
            <SetInputGrid
              values={seqValues}
              onChangeAt={(index, value) => setSeqValues((prev) => replaceAt(prev, index, value))}
              ariaLabelPrefix="Подход"
            />
            <div className="workout-mode-buttons">
              <Button
                mode="outline"
                size="s"
                disabled={seqValues.length <= (type.min_count ?? 1)}
                onClick={() => setSeqValues((prev) => prev.slice(0, -1))}
              >
                − подход
              </Button>
              <Button
                mode="outline"
                size="s"
                disabled={seqValues.length >= (type.max_count ?? seqValues.length)}
                onClick={() => setSeqValues((prev) => [...prev, ""])}
              >
                + подход
              </Button>
            </div>
          </Section>
        )}

        {formError && <p className="error-banner">{formError}</p>}
        <Button
          className="action-button"
          size="l"
          stretched
          disabled={submitting}
          onClick={() => void handleSubmit(type)}
        >
          Записать факультатив
        </Button>
        <Button
          className="action-button"
          size="l"
          stretched
          mode="outline"
          disabled={submitting}
          onClick={() => setState({ phase: "picker", plan })}
        >
          ← Выбрать другой формат
        </Button>
      </div>
    );
  }

  const { plan } = state;
  return (
    <div>
      <p className="plan-title">Факультатив</p>
      {plan.is_rest_day && (
        <p className="gap-banner">
          Сегодня день отдыха{plan.ready_at ? ` — обычная тренировка снова доступна ${plan.ready_at}` : ""}. Можешь
          вместо этого сделать факультатив — доп. нагрузку, которая не тронет план.
        </p>
      )}
      <p className="hint">
        Не более {plan.elective_limit} раз в неделю — уже сделано {plan.entries_this_week} из {plan.elective_limit}.
      </p>

      {!plan.elective_allowed && (
        <Placeholder description="Факультативы на этой неделе уже использованы — новый будет доступен на следующей неделе." />
      )}

      {plan.elective_allowed &&
        plan.available_types.map((type) => (
          <Button
            key={type.value}
            className="action-button"
            size="l"
            stretched
            mode="outline"
            onClick={() => chooseType(plan, type)}
          >
            {type.label}
          </Button>
        ))}

      <Button className="action-button" size="l" stretched mode="outline" onClick={onCancel}>
        Назад
      </Button>
    </div>
  );
}
