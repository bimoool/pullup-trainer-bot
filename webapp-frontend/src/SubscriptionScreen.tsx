import { openLink } from "@telegram-apps/sdk";
import { Button, Cell, Placeholder, Section, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchSubscription, paySubscription, type SubscriptionResponse } from "./api";

type Props = { initDataRaw: string; onBack: () => void };

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; subscription: SubscriptionResponse };

const OFERTA_URL = "/api/oferta.pdf";

/** Открывает ссылку вне Mini App (issue #53, волна 2; переиспользуется для
 * оферты — issue #57, п.2) — двойной фолбэк, тот же приём, что уже
 * применён в App.tsx для initData: сначала openLink() из
 * @telegram-apps/sdk (issue #15 — не парсить window.Telegram.WebApp
 * руками), при недоступности/ошибке — window.Telegram.WebApp.openLink
 * (мост telegram-web-app.js, независимый от SDK), финальный фолбэк
 * window.open — для разработки вне Telegram, где оба метода выше не
 * существуют. Mini App не закрывается ни в одном из путей — для оплаты
 * подтверждение приходит отдельным воркером sync_robokassa_payments, для
 * оферты закрывать вовсе не нужно (просто открывает PDF в браузере). */
function openExternalLink(url: string) {
  try {
    if (openLink.isAvailable()) {
      openLink(url);
      return;
    }
  } catch {
    // падаем в фолбэк ниже
  }
  const telegramWebApp = (window as unknown as { Telegram?: { WebApp?: { openLink?: (u: string) => void } } })
    .Telegram?.WebApp;
  if (telegramWebApp?.openLink) {
    telegramWebApp.openLink(url);
    return;
  }
  window.open(url, "_blank");
}

/** "Подписка" Mini App (issue #57, п.1) — раньше этот раздел был частью
 * вкладки "Профиль" (issue #53, волна 2), но там он оказался слишком
 * заметным сразу при открытии — вынесен в свой экран, на "Профиль"
 * остаётся только краткая строка статуса (см. ProfileScreen.tsx).
 *
 * Больше не отдельный пункт нижнего меню (issue #74, волна 4 — меню
 * разрослось до 6 пунктов, названия переставали помещаться): открывается
 * только кнопкой "⭐ Подробнее о подписке" с "Профиля", поэтому теперь
 * нужна явная кнопка "Назад" — без пункта меню на этот экран больше не
 * возвращает переключение вкладок.
 *
 * `Section`/`Cell`/`Placeholder` вместо `.profile-card`/`.screen-message`
 * (issue #142) — тот же базовый паттерн, что AchievementsScreen.tsx. */
export function SubscriptionScreen({ initDataRaw, onBack }: Props) {
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
        <Placeholder>
          <Spinner size="m" />
        </Placeholder>
      </div>
    );
  }
  if (state.phase === "error") {
    return (
      <div>
        <Button mode="outline" size="s" onClick={onBack}>
          ← Профиль
        </Button>
        <Placeholder description={`Не удалось загрузить подписку: ${state.message}`} />
      </div>
    );
  }

  const { subscription } = state;
  return (
    <div>
      <Button mode="outline" size="s" onClick={onBack}>
        ← Профиль
      </Button>

      <Section header="Подписка">
        <Cell subtitle={subscription.status_label ?? "Статус подписки недоступен."}>Статус</Cell>
        {subscription.robokassa_available ? (
          <Button mode="filled" size="m" stretched onClick={() => void handlePay()} loading={paying}>
            💳 Оплатить {subscription.price_rub} ₽ / {subscription.days} дн.
          </Button>
        ) : (
          <Placeholder description="Оплата картой временно недоступна." />
        )}
        {payError && <Placeholder description={`Не удалось создать ссылку на оплату: ${payError}`} />}
        <div className="pricing-text" dangerouslySetInnerHTML={{ __html: subscription.pricing_text_html }} />
        <Button
          mode="outline"
          size="m"
          stretched
          onClick={() => openExternalLink(new URL(OFERTA_URL, window.location.origin).toString())}
        >
          📄 Открыть текст оферты
        </Button>
      </Section>
    </div>
  );
}
