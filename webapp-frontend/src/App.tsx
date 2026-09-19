import {
  hideBackButton,
  mountBackButton,
  onBackButtonClick,
  retrieveLaunchParams,
  showBackButton,
} from "@telegram-apps/sdk";
import { Tabbar } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchHello, type HelloResponse } from "./api";
import { DashboardScreen } from "./DashboardScreen";
import { DashboardV2Screen } from "./DashboardV2Screen";
import { FaqScreen } from "./FaqScreen";
import { HistoryScreen } from "./HistoryScreen";
import { HomeScreen } from "./HomeScreen";
import { OnboardingScreen } from "./OnboardingScreen";
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
 * — открыть разминку можно только оттуда).
 *
 * "dashboard"/"plans" (issue #175, волна 4) — стартовым экраном было
 * "Dashboard": сводка (стрик, счётчики, статус готовности) вместо сразу
 * открытой формы тренировки (product-reference skill, референс — Crimpd).
 * Волна 5b (issue #183, crimpd-reference skill) развела это на пять вкладок
 * по референсу: сама сводка (DashboardScreen.tsx, без изменений содержимого)
 * переехала под ключом "plans" во вкладку "Планы", а стартовым экраном стал
 * новый компактный "home" (HomeScreen.tsx) — виджет "на этой неделе" сверху
 * + честная заглушка под каталог курсов (волна 6, ещё не сделан). "Начать
 * тренировку" что с "home", что с "plans" одинаково переключает на
 * "workout" — форма по-прежнему не дублируется, просто вкладки нижнего меню
 * у неё больше нет (открывается только отсюда, back — ниже). */
/* "dashboardV2" (issue #167, волна 4) — экспериментальный экран новой
 * многокурсовой схемы (эндпоинты новой версии API). Невидимая вкладка, добавляется в нижнее
 * меню условно и только для ADMIN_IDS (hello.is_admin) — это НЕ стартовый
 * экран "home"/"plans" выше, а отдельный испытательный стенд рядом с ними. */
type Tab = "home" | "plans" | "workout" | "history" | "progress" | "profile" | "subscription" | "faq" | "warmup" | "dashboardV2";

const NAV_TABS: { key: Tab; icon: string; label: string }[] = [
  { key: "home", icon: "🏠", label: "Главная" },
  { key: "plans", icon: "🗓", label: "Планы" },
  { key: "history", icon: "📜", label: "Журнал" },
  { key: "progress", icon: "📈", label: "Аналитика" },
  { key: "profile", icon: "👤", label: "Профиль" },
];

/** Куда ведёт аппаратная/телеграмная кнопка "назад" (telegram-miniapp
 * skill: обрабатывается через @telegram-apps/sdk, не руками) — null для
 * вкладок нижнего меню, у них назад некуда, сама Tabbar остаётся видимой.
 * "warmup"/"subscription" всегда возвращают на конкретный экран (открыты
 * только оттуда), "workout"/"faq" запоминают, откуда открыли (см.
 * workoutReturnTab/faqReturnTab). */
function backTargetFor(tab: Tab, workoutReturnTab: Tab, faqReturnTab: Tab): Tab | null {
  switch (tab) {
    case "workout":
      return workoutReturnTab;
    case "faq":
      return faqReturnTab;
    case "warmup":
      return "workout";
    case "subscription":
      return "profile";
    default:
      return null;
  }
}

const DASHBOARD_V2_NAV_TAB: { key: Tab; icon: string; label: string } = {
  key: "dashboardV2", icon: "🧪", label: "Dashboard",
};

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
  const [tab, setTab] = useState<Tab>("home");
  // Живая тренировка (issue #59) держит несохранённый ввод только во
  // фронтенд-состоянии до финальной отправки (LiveWorkoutScreen.tsx) —
  // переключение вкладок размонтировало бы WorkoutScreen вместе с ней и
  // потеряло бы прогресс молча, поэтому переключение вкладок при активной
  // живой тренировке сначала спрашивает подтверждение.
  const [liveWorkoutActive, setLiveWorkoutActive] = useState(false);
  // FAQ (issue #102) открывается и с "Профиля", и сноской у выбора резины
  // на "Тренировке" — запоминаем, откуда пришли, чтобы "Назад" вёл туда же.
  const [faqReturnTab, setFaqReturnTab] = useState<Tab>("profile");
  // "Тренировка" (issue #183, волна 5b) больше не пункт нижнего меню —
  // открывается кнопкой с "Главной" или с "Планов", запоминаем, откуда,
  // ровно тем же приёмом, что faqReturnTab выше.
  const [workoutReturnTab, setWorkoutReturnTab] = useState<Tab>("home");

  function openFaq(from: Tab) {
    setFaqReturnTab(from);
    setTab("faq");
  }

  function openWorkout(from: Tab) {
    setWorkoutReturnTab(from);
    setTab("workout");
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

  // Аппаратная/телеграмная кнопка "назад" (telegram-miniapp skill: только
  // через @telegram-apps/sdk, не руками) — показана ровно на экранах,
  // открытых не из нижнего меню (backTargetFor выше), ведёт назад тем же
  // guarded-путём, что и клик по вкладке (не в обход подтверждения потери
  // прогресса живой тренировки — та же проверка, что в handleTabClick).
  // ifAvailable() молча ничего не делает вне Telegram (e2e/обычный
  // браузер) — Tabbar остаётся видимой и служит запасным выходом с любого
  // экрана независимо от этого.
  useEffect(() => {
    const target = backTargetFor(tab, workoutReturnTab, faqReturnTab);
    if (target === null) {
      hideBackButton.ifAvailable();
      return;
    }
    mountBackButton.ifAvailable();
    showBackButton.ifAvailable();
    const off = onBackButtonClick.ifAvailable(() => {
      if (liveWorkoutActive && !window.confirm("Прогресс тренировки будет потерян — уйти?")) {
        return;
      }
      setTab(target);
    });
    return () => {
      off?.();
      hideBackButton.ifAvailable();
    };
  }, [tab, workoutReturnTab, faqReturnTab, liveWorkoutActive]);

  // Переиспользуется и начальной загрузкой, и завершением онбординга
  // (OnboardingScreen.tsx::onComplete, issue #124, PR 2) — initDataRaw уже
  // известна (Telegram-цепочка ниже проходится только один раз, при первом
  // открытии), новый GET /api/hello просто приносит свежий onboarding_step.
  async function refetchHello(initDataRaw: string) {
    try {
      const data = await fetchHello(initDataRaw);
      setState({ status: "ready", data, initDataRaw });
    } catch (error) {
      setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
    }
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

  const isOnboarded = state.data.onboarding_step === "done";

  // Экспериментальная вкладка новой схемы видна только тестировщикам

  const navTabs = state.data.is_admin ? [...NAV_TABS, DASHBOARD_V2_NAV_TAB] : NAV_TABS;

  return (
    <div className={isOnboarded ? "app-shell app-shell-with-nav" : "app-shell"}>
      <p className="app-greeting">Привет, {state.data.name}!</p>
      {/* Замер + анкета (issue #124, PR 2) — раньше единственным путём
          пройти онбординг был бот ("Онбординг ещё не пройден. Начни его в
          боте."), теперь полноценный экран прямо здесь: не нужно закрывать
          Mini App и переключаться в чат с ботом, чтобы вообще начать. */}
      {!isOnboarded && (
        <OnboardingScreen
          initDataRaw={state.initDataRaw}
          startStep={state.data.onboarding_step}
          onComplete={() => void refetchHello(state.initDataRaw)}
        />
      )}
      {isOnboarded && tab === "home" && (
        <HomeScreen initDataRaw={state.initDataRaw} onOpenWorkout={() => openWorkout("home")} />
      )}
      {isOnboarded && tab === "plans" && (
        <DashboardScreen initDataRaw={state.initDataRaw} onOpenWorkout={() => openWorkout("plans")} />
      )}
      {isOnboarded && tab === "workout" && (
        <WorkoutScreen
          initDataRaw={state.initDataRaw}
          onLiveActiveChange={setLiveWorkoutActive}
          onOpenFaq={() => openFaq("workout")}
          onOpenWarmup={() => setTab("warmup")}
        />
      )}
      {isOnboarded && tab === "history" && <HistoryScreen initDataRaw={state.initDataRaw} />}
      {isOnboarded && tab === "progress" && <ProgressScreen initDataRaw={state.initDataRaw} />}
      {isOnboarded && tab === "profile" && (
        <ProfileScreen
          initDataRaw={state.initDataRaw}
          onOpenSubscription={() => setTab("subscription")}
          onOpenFaq={() => openFaq("profile")}
        />
      )}
      {isOnboarded && tab === "subscription" && (
        <SubscriptionScreen initDataRaw={state.initDataRaw} onBack={() => setTab("profile")} />
      )}
      {isOnboarded && tab === "faq" && (
        <FaqScreen initDataRaw={state.initDataRaw} onBack={() => setTab(faqReturnTab)} />
      )}
      {isOnboarded && tab === "warmup" && (
        <WarmupScreen initDataRaw={state.initDataRaw} onBack={() => setTab("workout")} />
      )}
      {isOnboarded && tab === "dashboardV2" && (
        <DashboardV2Screen initDataRaw={state.initDataRaw} onGoToWorkout={() => setTab("workout")} />
      )}

      {isOnboarded && (
        <Tabbar>
          {navTabs.map(({ key, icon, label }) => (
            <Tabbar.Item key={key} text={label} selected={tab === key} onClick={() => handleTabClick(key)}>
              <span className="bottom-nav-icon">{icon}</span>
            </Tabbar.Item>
          ))}
        </Tabbar>
      )}
    </div>
  );
}
