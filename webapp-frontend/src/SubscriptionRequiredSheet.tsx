import { Button } from "@telegram-apps/telegram-ui";

import { FormSheet } from "./FormSheet";
import { openSubscriptionScreen } from "./paywall";
import { useBackButton } from "./useBackButton";

type Props = { message: string | null; onOpenSubscription: () => void; onClose: () => void };

/**
 * Решение владельца 2026-10-17: Premium-функция без подписки (сервер ответил 402 subscription_required). Лист поверх
 * текущего экрана: экран под ним не размонтируется, поэтому введённое в форму сохраняется — после оформления
 * подписки можно вернуться и отправить ещё раз. Без обещаний результата — только что доступно бесплатно и где оплатить.
 */
export function SubscriptionRequiredSheet({ message, onOpenSubscription, onClose }: Props) {
  useBackButton(onClose, [onClose]);
  return (
    <FormSheet title="Нужна подписка" onClose={onClose}>
      <div className="subscription-required-sheet" data-testid="subscription-required-sheet">
        <h2 className="subscription-required-title">Нужна подписка</h2>
        <p className="screen-message">
          {message ?? "Эта функция доступна с подпиской. Программа «Подтягивания» остаётся бесплатной."}
        </p>
        <p className="screen-message">
          Бесплатно без ограничений: программа «Подтягивания» — тесты, основные тренировки, её факультативы, план,
          история и прогресс. Дополнительные занятия, свои упражнения и тренировки, другие программы и экспорт
          истории — по подписке. Введённые данные на экране сохранены.
        </p>
        <Button className="action-button vs-primary" size="l" stretched onClick={onOpenSubscription}>
          Открыть подписку
        </Button>
        <Button className="action-button vs-plain" size="l" stretched mode="plain" onClick={onClose}>
          Не сейчас
        </Button>
      </div>
    </FormSheet>
  );
}

/** То же объяснение заранее, прямо на экране Premium-функции (сервер отдал subscription_required в GET): предложение
 * видно, форма остаётся, кнопка открывает экран подписки поверх (введённое не теряется). */
export function PremiumFeatureNotice({ feature }: { feature: string }) {
  return (
    <div className="premium-feature-notice" data-testid="premium-feature-notice" role="note">
      <p className="screen-message">
        {feature} — по подписке. Программа «Подтягивания» остаётся бесплатной: тесты, основные тренировки, план и
        история доступны без оплаты.
      </p>
      <Button className="action-button vs-primary" size="m" stretched onClick={openSubscriptionScreen}>
        Открыть подписку
      </Button>
    </div>
  );
}
