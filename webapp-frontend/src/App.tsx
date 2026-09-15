import { retrieveLaunchParams } from "@telegram-apps/sdk";
import { Tabbar } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchHello, type HelloResponse } from "./api";
import { FaqScreen } from "./FaqScreen";
import { HistoryScreen } from "./HistoryScreen";
import { ProfileScreen } from "./ProfileScreen";
import { ProgressScreen } from "./ProgressScreen";
import { SubscriptionScreen } from "./SubscriptionScreen";
import { WarmupScreen } from "./WarmupScreen";
import { WorkoutScreen } from "./WorkoutScreen";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: HelloResponse; initDataRaw: string };

/** Базовая навигация (issue #45, часть 3) — задел под структуру, не
 * перенос всего функционала бота: разделы добавляются одной записью в
 * NAV_TABS + веткой в рендере ниже (issue #50 добавила "История"/"Прогресс").
 *
 * issue #74, волна 4 — меню разрослось до 6 пунктов (после issue #57 п.1
 * "Подписки" и issue #67 "Лидерборда"), названия переставали помещаться.
 * Двухуровневая структура вместо этого: "Лидерборд" переехал под-разделом
 * внутри "Прогресса" (см. ProgressScreen.tsx — логически ближе, чем
 * "Профиль", обе вкладки про динамику результатов), "Подписка" осталась
 * отдельным экраном, но без своего пункта меню — открывается только кнопкой
 * с "Профиля" (тот же принцип, что у AchievementsScreen: "subscription" —
 * по-прежнему валидное значение Tab, просто не перечислено в NAV_TABS, так
 * что назад ведёт explicit onBack, не переключение вкладки).
 *
 * "faq" (issue #102) — тот же приём: не пункт нижнего меню, открывается
 * кнопкой с "Профиля" ИЛИ сноской у выбора резины на WorkoutScreen (два
 * разных входа в один и тот же экран, в отличие от "subscription", у
 * которого один вход). faqReturnTab ниже помнит, откуда открыли, чтобы
 * "Назад" вёл туда же, а не всегда на "Профиль".
 *
 * "warmup" (issue #124, PR 1) — тот же приём, что "faq": один вход, с
 * кнопки "🔥 Показать разминку" на WorkoutScreen, "Назад" всегда ведёт на
 * "Тренировку" (в отличие от "faq", запоминать возвратную вкладку не нужно
 * — открыть разминку можно только оттуда). */
type Tab = "workout" | "history" | "progress" | "profile" | "subscription" | "faq" | "warmup";

const NAV_TABS: { key: Tab; icon: string; label: string }[] = [
  { key: "workout", icon: "💪", label: "Тренировка" },
  { key: "history", icon: "📜", label: "История" },
  { key: "progress", icon: "📈", label: "Прогресс" },
  { key: "profile", icon: "👤", label: "Профиль" },
];

type TelegramWebApp = { initData?: string; version?: string; platform?: string };

/**
 * issue #28 — предыдущий текст ошибки ("initDataRaw is empty — открыто не
 * из Telegram?") был одинаков и для реального бага (initData не долетел),
 * и для заведомо ожидаемого случая (страница открыта напрямую в обычном
 * браузере — там initData не появится никогда, ни при какой конфигурации
 * кнопки). Со стороны пользователя оба выглядят идентично, что и породило
 * ложный след в issue: кнопка в app/bot/keyboards.py уже
 * KeyboardButton(web_app=WebAppInfo(...)), не обычная url= ссылка — код
 * это подтверждает, а сам факт "то же самое в браузере" ничего не
 * доказывает. Раз ошибка внутри настоящего Telegram-клиента всё равно
 * повторяется — точку отказа даёт только больше сырых данных с места
 * (что вернул retrieveLaunchParams, есть ли вообще window.Telegram.WebApp,
 * какой у него version/platform), не гадание по одной фразе.
 */
function describeInitDataFailure(retrieveError: string | undefined, telegramWebApp: TelegramWebApp | undefined) {
  const parts = [
    `retrieveLaunchParams: ${retrieveError ?? "вернул пустой initDataRaw без исключения"}`,
    telegramWebApp
      ? `window.Telegram.WebApp: есть (version=${telegramWebApp.version ?? "?"}, platform=${telegramWebApp.platform ?? "?"})`
      : "window.Telegram.WebApp: отсутствует",
    `location.href: ${window.location.href}`,
  ];
  return parts.join(" | ");
}

export function App() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [tab, setTab] = useState<Tab>("workout");
  // Живая тренировка (issue #59) держит несохранённый ввод только во
  // фронтенд-состоянии до финальной отправки (LiveWorkoutScreen.tsx) —
  // переключение вкладок размонтировало бы WorkoutScreen вместе с ней и
  // потеряло бы прогресс молча, поэтому переключение вкладок при активной
  // живой тренировке сначала спрашивает подтверждение.
  const [liveWorkoutActive, setLiveWorkoutActive] = useState(false);
  // FAQ (issue #102) открывается и с "Профиля", и сноской у выбора резины
  // на "Тренировке" — запоминаем, откуда пришли, чтобы "Назад" вёл туда же.
  const [faqReturnTab, setFaqReturnTab] = useState<Tab>("profile");

  function openFaq(from: Tab) {
    setFaqReturnTab(from);
    setTab("faq");
  }

  function handleTabClick(key: Tab) {
    if (key === tab) {
      return;
    }
    if (liveWorkoutActive && !window.confirm("Прогресс тренировки будет потерян — уйти?")) {
      return;
    }
    setTab(key);
  }

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        // Этап 0 (issue #15) — доказательство цепочки целиком: initData
        // (Telegram) → HTTPS → FastAPI → проверка подписи → те же
        // repositories/domain, что у бота. retrieveLaunchParams — из
        // @telegram-apps/sdk (issue #15: не парсить window.Telegram.WebApp
        // руками), initDataRaw — то же самое, что видит app/web/auth.py.
        //
        // issue #23: на живом Telegram Desktop retrieveLaunchParams()
        // отдавал initDataRaw пустым, хотя Mini App открыт кнопкой
        // KeyboardButton(web_app=...) — правильным способом (initData
        // передаётся по документации Bot API, см. app/bot/keyboards.py).
        // retrieveLaunchParams() читает launch params из URL (hash/query),
        // куда их вписывает клиент при открытии; window.Telegram.WebApp.initData
        // — тот же самый initData, но из моста telegram-web-app.js
        // (грузится напрямую в index.html), не зависящего от разбора URL —
        // если клиент не положил launch params в URL, но мост всё равно
        // получил initData, это не даёт финального "не в Telegram", а
        // просто означает, что нужен запасной источник.
        let initDataRaw: string | undefined;
        let retrieveError: string | undefined;
        try {
          initDataRaw = retrieveLaunchParams().initDataRaw;
        } catch (error) {
          retrieveError = error instanceof Error ? error.message : String(error);
        }
        const telegramWebApp = (window as unknown as { Telegram?: { WebApp?: TelegramWebApp } }).Telegram?.WebApp;
        if (!initDataRaw) {
          initDataRaw = telegramWebApp?.initData;
        }
        if (!initDataRaw) {
          throw new Error(
            `initDataRaw is empty — открыто не из Telegram? [${describeInitDataFailure(retrieveError, telegramWebApp)}]`,
          );
        }
        const data = await fetchHello(initDataRaw);
        if (!cancelled) {
          setState({ status: "ready", data, initDataRaw });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.status === "loading") {
    return (
      <div className="app-shell">
        <p className="screen-message">Загрузка…</p>
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="app-shell">
        <p className="screen-message">Не удалось загрузить: {state.message}</p>
      </div>
    );
  }

  return (
    <div className={state.data.is_onboarded ? "app-shell app-shell-with-nav" : "app-shell"}>
      <p className="app-greeting">Привет, {state.data.name}!</p>
      {!state.data.is_onboarded && <p className="screen-message">Онбординг ещё не пройден. Начни его в боте.</p>}
      {state.data.is_onboarded && tab === "workout" && (
        <WorkoutScreen
          initDataRaw={state.initDataRaw}
          onLiveActiveChange={setLiveWorkoutActive}
          onOpenFaq={() => openFaq("workout")}
          onOpenWarmup={() => setTab("warmup")}
        />
      )}
      {state.data.is_onboarded && tab === "history" && <HistoryScreen initDataRaw={state.initDataRaw} />}
      {state.data.is_onboarded && tab === "progress" && <ProgressScreen initDataRaw={state.initDataRaw} />}
      {state.data.is_onboarded && tab === "profile" && (
        <ProfileScreen
          initDataRaw={state.initDataRaw}
          onOpenSubscription={() => setTab("subscription")}
          onOpenFaq={() => openFaq("profile")}
        />
      )}
      {state.data.is_onboarded && tab === "subscription" && (
        <SubscriptionScreen initDataRaw={state.initDataRaw} onBack={() => setTab("profile")} />
      )}
      {state.data.is_onboarded && tab === "faq" && (
        <FaqScreen initDataRaw={state.initDataRaw} onBack={() => setTab(faqReturnTab)} />
      )}
      {state.data.is_onboarded && tab === "warmup" && (
        <WarmupScreen initDataRaw={state.initDataRaw} onBack={() => setTab("workout")} />
      )}

      {state.data.is_onboarded && (
        <Tabbar>
          {NAV_TABS.map(({ key, icon, label }) => (
            <Tabbar.Item key={key} text={label} selected={tab === key} onClick={() => handleTabClick(key)}>
              <span className="bottom-nav-icon">{icon}</span>
            </Tabbar.Item>
          ))}
        </Tabbar>
      )}
    </div>
  );
}
