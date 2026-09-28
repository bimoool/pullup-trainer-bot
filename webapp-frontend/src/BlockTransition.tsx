import { Button, Section } from "@telegram-apps/telegram-ui";

import type { LiveSessionBlockResponse } from "./apiV2";
import { describeBlockPlan } from "./blockFormat";

type Props = {
  block: LiveSessionBlockResponse;
  /** Имя следующего упражнения; null — человекочитаемого имени нет
   * (internal STEP-роль), строка называет только план. */
  name: string | null;
  starting: boolean;
  error: string | null;
  onStart: () => void;
};

/**
 * R1 — interstitial между блоками смешанной тренировки: предыдущий блок
 * завершён, следующий НЕ стартует сам, пока пользователь явно не нажмёт
 * "Начать". Skip намеренно нет.
 */
export function BlockTransition({ block, name, starting, error, onStart }: Props) {
  const plan = describeBlockPlan(block.protocol_type, block.targets, block.interval_config);
  return (
    <Section className="block-section phase-card-done" header="Готово ✓">
      <p className="block-subtitle">Следующее упражнение</p>
      <p className="plan-title">{[name, plan].filter((part) => part !== null).join(" · ")}</p>
      {error && <p className="gap-banner">Не удалось начать: {error}. Попробуйте ещё раз.</p>}
      <Button className="action-button" size="l" stretched disabled={starting} onClick={onStart}>
        Начать
      </Button>
    </Section>
  );
}
