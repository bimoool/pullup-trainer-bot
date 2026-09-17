import { Button, Placeholder, Section, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchWarmup } from "./api";

type Props = { initDataRaw: string; onBack: () => void };

type ScreenState = { phase: "loading" } | { phase: "error"; message: string } | { phase: "ready"; textHtml: string };

/** Разминка (issue #124, PR 1) — первый бот-only кусок, перенесённый в Mini
 * App: тот же texts.WARMUP_FULL, что бот показывает перед первой тренировкой
 * блока и по кнопке "Показать разминку" (app/bot/handlers/workout.py::
 * handle_warmup_show). Открывается кнопкой с "Тренировки" (WorkoutScreen.tsx)
 * — тот же приём навигации, что FaqScreen (не пункт нижнего меню, "warmup" —
 * валидное значение Tab в App.tsx, назад ведёт на тот раздел, откуда
 * открыли).
 * `Placeholder`/`Spinner`/`Section` вместо `.screen-message`/`.profile-card`
 * (issue #142) — тот же базовый паттерн, что AchievementsScreen.tsx/FaqScreen.tsx. */
export function WarmupScreen({ initDataRaw, onBack }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const { text_html: textHtml } = await fetchWarmup(initDataRaw);
        if (!cancelled) {
          setState({ phase: "ready", textHtml });
        }
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

  return (
    <div>
      <Button mode="outline" size="s" onClick={onBack}>
        ← Назад
      </Button>
      <p className="plan-title">🔥 Разминка перед тренировкой</p>

      {state.phase === "loading" && (
        <Placeholder>
          <Spinner size="m" />
        </Placeholder>
      )}
      {state.phase === "error" && <Placeholder description={`Не удалось загрузить разминку: ${state.message}`} />}
      {state.phase === "ready" && (
        <Section>
          <div className="pricing-text" dangerouslySetInnerHTML={{ __html: state.textHtml }} />
        </Section>
      )}
    </div>
  );
}
