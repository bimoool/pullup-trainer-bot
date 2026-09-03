import { openLink } from "@telegram-apps/sdk";
import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchProfile, fetchSubscription, paySubscription, type ProfileResponse, type SubscriptionResponse } from "./api";

type Props = { initDataRaw: string };

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; profile: ProfileResponse; subscription: SubscriptionResponse };

/** Открывает ссылку на оплату вне Mini App (issue #53, волна 2) — тот же
 * приём двойного фолбэка, что уже применён в App.tsx для initData: сначала
 * openLink() из @telegram-apps/sdk (issue #15 — не парсить
 * window.Telegram.WebApp руками), при недоступности/ошибке —
 * window.Telegram.WebApp.openLink (мост telegram-web-app.js, независимый
 * от SDK), финальный фолбэк window.open — для разработки вне Telegram, где
 * оба метода выше не существуют. Mini App не закрывается ни в одном из
 * путей — оплата подтверждается воркером sync_robokassa_payments отдельно
 * от текущей сессии Mini App. */
function openPaymentLink(url: string) {
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

/** Вкладка "Профиль" Mini App (issue #45, часть 3; раздел подписки — issue
 * #53, волна 2) — сознательно узкий первый шаг: подписка, монеты, число
 * тренировок/ачивок, дни с последней тренировки. Полный профиль
 * (рост/вес/таймзона/список ачивок текстом) остаётся только в боте
 * (app/bot/handlers/menu.py::render_profile) — сюда можно добавлять поля
 * по одному, когда понадобится, не всё сразу. */
export function ProfileScreen({ initDataRaw }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [paying, setPaying] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [profile, subscription] = await Promise.all([
          fetchProfile(initDataRaw),
          fetchSubscription(initDataRaw),
        ]);
        if (!cancelled) {
          setState({ phase: "ready", profile, subscription });
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
      openPaymentLink(paymentUrl);
    } catch (error) {
      setPayError(error instanceof Error ? error.message : String(error));
    } finally {
      setPaying(false);
    }
  }

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю профиль…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить профиль: {state.message}</p>;
  }

  const { profile, subscription } = state;
  if (!profile.is_onboarded) {
    return <p className="screen-message">Онбординг ещё не пройден. Начни его в боте.</p>;
  }

  return (
    <div>
      <p className="plan-title">Профиль</p>

      <div className="profile-card">
        <p>
          {profile.days_since_last_workout === null
            ? "Тренировок пока не было."
            : profile.days_since_last_workout === 0
              ? "Последняя тренировка — сегодня."
              : `Последняя тренировка: ${profile.days_since_last_workout} дн. назад.`}
        </p>
      </div>

      {/* Раздел подписки/оплаты (issue #53, волна 2) — Stars-оплата здесь
       * сознательно не показывается, только Робокасса (см. текст issue):
       * нативная Stars-подписка устроена иначе и остаётся только в боте. */}
      <div className="profile-card">
        <p className="section-title">Подписка</p>
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
      </div>

      <div className="stat-grid">
        <div className="stat-tile">
          <div className="stat-value">{profile.workouts_count}</div>
          <div className="stat-label">Тренировок</div>
        </div>
        <div className="stat-tile">
          <div className="stat-value">{profile.achievements_count}</div>
          <div className="stat-label">Ачивок</div>
        </div>
        <div className="stat-tile">
          <div className="stat-value">{profile.coins_balance}</div>
          <div className="stat-label">Монет</div>
        </div>
      </div>
    </div>
  );
}
