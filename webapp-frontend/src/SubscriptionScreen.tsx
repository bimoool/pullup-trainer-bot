import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchSubscription, paySubscription, type SubscriptionResponse } from "./api";
import { openExternalLink } from "./telegramLinks";
import { useBackButton } from "./useBackButton";

type Props = { initDataRaw: string; onBack: () => void };

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; subscription: SubscriptionResponse };

export const OFERTA_URL = "/api/oferta.pdf";

// openExternalLink вынесен в telegramLinks.ts (его же использует экспорт CSV, #224).
export { openExternalLink };

/** "Подписка" Mini App (issue #57, п.1) — раньше этот раздел был частью
 * вкладки "Профиль" (issue #53, волна 2), но там он оказался слишком
 * заметным сразу при открытии — вынесен в свой экран, на "Профиль"
 * остаётся только краткая строка статуса (см. ProfileScreen.tsx).
 *
 * Больше не отдельный пункт нижнего меню (issue #74, волна 4 — меню
 * разрослось до 6 пунктов, названия переставали помещаться): открывается
 * только кнопкой "⭐ Подробнее о подписке" с "Профиля", поэтому теперь
 * нужна явная кнопка "Назад" — без пункта меню на этот экран больше не
 * возвращает переключение вкладок. */
export function SubscriptionScreen({ initDataRaw, onBack }: Props) {
  // Telegram BackButton вместо/вместе с «← Назад» (#224): тот же обработчик, что у видимой кнопки.
  useBackButton(onBack, [onBack]);
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [paying, setPaying] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const subscription = await fetchSubscription(initDataRaw);
        if (!cancelled) {
          setState({ phase: "ready", subscription });
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

  async function handlePay() {
    setPayError(null);
    setPaying(true);
    try {
      const { payment_url: paymentUrl } = await paySubscription(initDataRaw);
      openExternalLink(paymentUrl);
    } catch (error) {
      setPayError(error instanceof Error ? error.message : String(error));
    } finally {
      setPaying(false);
    }
  }

  if (state.phase === "loading") {
    return (
      <div>
        <Button mode="outline" size="s" onClick={onBack}>
          ← Профиль
        </Button>
        <p className="screen-message">Загружаю подписку…</p>
      </div>
    );
  }
  if (state.phase === "error") {
    return (
      <div>
        <Button mode="outline" size="s" onClick={onBack}>
          ← Профиль
        </Button>
        <p className="screen-message">Не удалось загрузить подписку: {state.message}</p>
      </div>
    );
  }

  const { subscription } = state;
  return (
    <div>
      <Button mode="outline" size="s" onClick={onBack}>
        ← Профиль
      </Button>
      <p className="plan-title">Подписка</p>

      <div className="profile-card">
        <p className="section-title">Статус</p>
        <p>{subscription.status_label ?? "Статус подписки недоступен."}</p>
        {subscription.robokassa_available ? (
          <Button mode="filled" size="m" stretched onClick={() => void handlePay()} loading={paying}>
            💳 Оплатить {subscription.price_rub} ₽ / {subscription.days} дн.
          </Button>
        ) : (
          <p className="screen-message">Оплата картой временно недоступна.</p>
        )}
        {payError && <p className="screen-message">Не удалось создать ссылку на оплату: {payError}</p>}
        <div className="pricing-text" dangerouslySetInnerHTML={{ __html: subscription.pricing_text_html }} />
        <Button
          mode="outline"
          size="m"
          stretched
          onClick={() => openExternalLink(new URL(OFERTA_URL, window.location.origin).toString())}
        >
          📄 Открыть текст оферты
        </Button>
      </div>
    </div>
  );
}
