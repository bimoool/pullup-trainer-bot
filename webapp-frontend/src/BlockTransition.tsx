import { Button } from "@telegram-apps/telegram-ui";

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
    <div className="phase-panel phase-card-done live-transition">
      <h2 className="phase-panel-label">Готово ✓</h2>
      <p className="live-transition-eyebrow">Следующее упражнение</p>
      {name !== null && <p className="live-exercise">{name}</p>}
      <p className="live-target">{plan}</p>
      {error && <p className="gap-banner">Не удалось начать: {error}. Попробуйте ещё раз.</p>}
      <Button className="action-button live-primary" size="l" stretched disabled={starting} onClick={onStart}>
        Начать
      </Button>
    </div>
  );
}
