import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchElectivePlan, type ElectivePlan } from "./api";
import { ELECTIVE_EXPLANATION, ELECTIVE_LIMIT_TEXT, ELECTIVE_REST_DAY_HINT, electiveCounterLabel } from "./planRows";

/**
 * UX-33 — входы в бесплатные факультативы из контекста курса/плана/Главной. Сам экран — прежний ElectiveScreen
 * (его монтируют вызывающие экраны, не здесь). Сводка читается из того же GET /api/elective/plan; её сбой не
 * ломает экран — блок просто не показывается.
 */
export function useElectiveSummary(initDataRaw: string, reloadKey: number): ElectivePlan | null {
  const [plan, setPlan] = useState<ElectivePlan | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchElectivePlan(initDataRaw)
      .then((data) => {
        if (!cancelled) {
          setPlan(data.status === "ready" ? data : null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPlan(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, reloadKey]);
  return plan;
}

/** Карточка курса: «Факультативы: N из 2 на этой неделе», одна строка пояснения, кнопка либо текст про лимит. */
export function ElectiveCourseLine({ plan, onOpen }: { plan: ElectivePlan | null; onOpen: () => void }) {
  if (plan === null) {
    return null;
  }
  return (
    <div className="ux-b-elective" data-testid="elective-course-line">
      <p className="block-subtitle" data-testid="elective-counter">
        {electiveCounterLabel(plan.entries_this_week, plan.elective_limit)}
      </p>
      <p className="hint" data-testid="elective-explanation">{ELECTIVE_EXPLANATION}</p>
      {plan.elective_allowed ? (
        <Button size="s" mode="outline" data-testid="elective-open" onClick={onOpen}>
          Сделать факультатив
        </Button>
      ) : (
        <p className="gap-banner" data-testid="elective-limit">{ELECTIVE_LIMIT_TEXT}</p>
      )}
    </div>
  );
}

/** Состояние «Сегодня отдых» в плане: пояснение и вход в факультатив (или честный текст про лимит). */
export function ElectiveRestDayBanner({ plan, onOpen }: { plan: ElectivePlan | null; onOpen: () => void }) {
  if (plan === null || !plan.is_rest_day) {
    return null;
  }
  return (
    <div className="ux-b-rest-day" data-testid="elective-rest-day">
      <p className="block-subtitle">{plan.elective_allowed ? ELECTIVE_REST_DAY_HINT : "Сегодня отдых"}</p>
      <p className="hint">{ELECTIVE_EXPLANATION}</p>
      {plan.elective_allowed ? (
        <Button size="s" mode="outline" data-testid="elective-rest-day-open" onClick={onOpen}>
          Сделать факультатив
        </Button>
      ) : (
        <p className="gap-banner" data-testid="elective-limit">{ELECTIVE_LIMIT_TEXT}</p>
      )}
    </div>
  );
}

/** Объяснение расписания курса словами (UX-06/32). */
export function CourseScheduleNote({ headline, consequence }: { headline: string; consequence: string | null }) {
  return (
    <div className="ux-b-schedule" data-testid="course-schedule">
      <p className="block-subtitle" data-testid="course-schedule-headline">{headline}</p>
      {consequence !== null && <p className="hint" data-testid="course-schedule-consequence">{consequence}</p>}
    </div>
  );
}
