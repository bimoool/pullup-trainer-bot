import { Button, Placeholder, Section, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchBandHelp } from "./api";

type Props = { initDataRaw: string; onBack: () => void };

type ScreenState = { phase: "loading" } | { phase: "error"; message: string } | { phase: "ready"; textHtml: string };

/** FAQ Mini App (issue #102) — первый отдельный FAQ-экран в вебе, открыт
 * кнопкой с "Профиля" и сноской у выбора резины на BAND (WorkoutScreen.tsx/
 * LiveWorkoutScreen.tsx), тот же приём навигации, что SubscriptionScreen
 * (не пункт нижнего меню — "faq" валидное значение Tab в App.tsx, назад
 * ведёт explicit onBack на тот раздел, откуда открыли, не всегда "Профиль").
 * Текст — не копия, а тот же texts.EQUIPMENT_BAND_HELP_TEXT, что кнопка
 * "❓ Как выбрать резину" бота (см. api.ts::fetchBandHelp).
 * `Placeholder`/`Spinner`/`Section` вместо `.screen-message`/`.profile-card`
 * (issue #142) — тот же базовый паттерн, что AchievementsScreen.tsx. */
export function FaqScreen({ initDataRaw, onBack }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const { text_html: textHtml } = await fetchBandHelp(initDataRaw);
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
      <p className="plan-title">Как выбрать резину</p>

      {state.phase === "loading" && (
        <Placeholder>
          <Spinner size="m" />
        </Placeholder>
      )}
      {state.phase === "error" && <Placeholder description={`Не удалось загрузить инструкцию: ${state.message}`} />}
      {state.phase === "ready" && (
        <Section>
          <div className="pricing-text" dangerouslySetInnerHTML={{ __html: state.textHtml }} />
        </Section>
      )}
    </div>
  );
}
