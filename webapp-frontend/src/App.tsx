import { useEffect, useRef, useState } from "react";

import { fetchDisplayPreferences, fetchHello, type HelloResponse } from "./api";
import { setDisplayPrefs } from "./displayPrefs";
import { fetchActiveLiveSession, type LiveSessionResponse } from "./apiV2";
import { DashboardScreen } from "./DashboardScreen";
import { drainQueuedFinish } from "./offlineSession";
import { PlanSessionFlow } from "./PlanSessionFlow";
import { FaqScreen } from "./FaqScreen";
import { HistoryScreen, type JournalRestore } from "./HistoryScreen";
import { HomeScreen } from "./HomeScreen";
import {
  getEngineReconcileStatus, startEngineReconciliation, subscribeEngineReconcileStatus, wakeEngineReconciliation,
} from "./liveEngineClient";
import { OnboardingScreen } from "./OnboardingScreen";
import { ProfileScreen } from "./ProfileScreen";
import { AnalyticsScreen } from "./AnalyticsScreen";
import { SessionV2Lab } from "./SessionV2Lab";
import { SubscriptionScreen } from "./SubscriptionScreen";
import { SubscriptionRequiredSheet } from "./SubscriptionRequiredSheet";
import { subscribeSubscriptionRequired } from "./paywall";
import { WarmupScreen } from "./WarmupScreen";
import { WorkoutScreen } from "./WorkoutScreen";
import { isSessionExpiredMessage } from "./sessionErrors";
import { confirmAction, getWebApp } from "./telegramPlatform";
import { useClosingConfirmation } from "./useClosingConfirmation";
import { resolveAuth } from "./platform/authBootstrap";
import { LoginScreen } from "./platform/LoginScreen";
import { AppShell } from "./platform/AppShell";
import { NavBar } from "./platform/NavBar";
import { PlatformProvider, usePlatform, usePlatformSetter } from "./platform/mode";
import { signOutBrowser } from "./platform/session";

/**
 * Сверка не смогла прочитать сохранённые очереди движка (IndexedDB). Там может лежать действие пользователя
 * (Стоп, пауза), поэтому чтения с проекцией (активная тренировка, Журнал) ждут — показываем причину;
 * повтор идёт сам (1, 2, 4, 8, 15 с), «Повторить» — сейчас. После удачного чтения баннер исчезает сам.
 */
function EngineStoreBanner() {
  const [unreadable, setUnreadable] = useState(getEngineReconcileStatus().storeUnreadable);
  useEffect(() => subscribeEngineReconcileStatus((status) => setUnreadable(status.storeUnreadable)), []);
  if (!unreadable) {
    return null;
  }
  return (
    <div className="error-banner" role="alert" data-testid="engine-store-error">
      <p>Не удалось прочитать сохранённые данные тренировки. Пробуем снова. Не очищайте данные приложения.</p>
      <button type="button" className="action-button" data-testid="engine-store-retry" onClick={() => wakeEngineReconciliation()}>
        Повторить
      </button>
    </div>
  );
}

type LoadState =
  | { status: "loading" }
  | { status: "login" }
  | { status: "error"; message: string }
  | { status: "ready"; data: HelloResponse; initDataRaw: string };

/** Базовая навигация (issue #45, часть 3) — задел под структуру, не
 * перенос всего функционала бота: разделы добавляются одной записью в
 * NAV_TABS + веткой в рендере ниже (issue #50 добавила "История"/"Прогресс").
 *
 * issue #74, волна 4 — меню разрослось до 6 пунктов (после issue #57 п.1
 * "Подписки" и issue #67 "Лидерборда"), названия переставали помещаться.
 * Двухуровневая структура вместо этого: "Лидерборд" переехал под-разделом
 * внутри "Прогресса"/"Аналитики" (см. ProgressScreen.tsx — логически ближе,
 * чем "Профиль", обе вкладки про динамику результатов), "Подписка" осталась
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
 * issue #183, волна 5b (crimpd-reference skill: "пять вкладок, как в
 * Crimpd") — нижнее меню перестроено на Главная/Планы/Журнал/Аналитика/
 * Профиль:
 *  - "workout" (issue #175: бывшая вкладка "Тренировка") ушёл из NAV_TABS
 *    совсем — та же схема, что у "subscription"/"faq"/"warmup" выше: валидное
 *    значение Tab без своего пункта меню, открывается кнопкой с "home" и
 *    "plans" (WorkoutScreen сам показывает нужное состояние, дублировать
 *    здесь нечего). Постоянный Tabbar ниже остаётся видимым и на этой
 *    вкладке — тот же неявный "назад" через переключение на любую другую
 *    вкладку, что уже работал для subscription/faq/warmup.
 *  - "dashboard" (issue #175, волна 4) переименован в "plans" — вся прежняя
 *    сводка (стрик, счётчики, статус готовности, DashboardScreen.tsx) осталась
 *    как есть, просто это больше не стартовый экран, а вкладка "Планы"
 *    (crimpd-reference, жёсткое правило №1: стартовый экран — каталог, не план).
 *  - новая "home" — стартовая вкладка, каталог (HomeScreen.tsx). Каталога
 *    ещё нет (волна 6) — честное пустое состояние вместо заглушки.
 *  - "history"/"progress" переименованы в "journal"/"analytics" — значения
 *    Tab и содержимое экранов не менялись, только ключ и заголовок. */
/* "dashboardV2" (issue #167, волна 4) — экспериментальный экран новой
 * многокурсовой схемы (эндпоинты новой версии API). Невидимая вкладка, добавляется в нижнее
 * меню условно и только для ADMIN_IDS (hello.is_admin) — это НЕ стартовый
 * экран "home" выше, а отдельный испытательный стенд рядом с ним. */
type Tab = "home" | "workout" | "plans" | "journal" | "analytics" | "profile" | "subscription" | "faq" | "warmup" | "dashboardV2";

const NAV_TABS: { key: Tab; label: string }[] = [
  { key: "home", label: "Главная" },
  { key: "plans", label: "Планы" },
  { key: "journal", label: "Журнал" },
  { key: "analytics", label: "Аналитика" },
  { key: "profile", label: "Профиль" },
];

const DASHBOARD_V2_NAV_TAB: { key: Tab; label: string } = {
  key: "dashboardV2", label: "Dashboard",
};

/** Workout Detail, с которого ушли в «Начать»/«Записать»: куда вернуть «назад». */
type WorkoutOrigin = { tab: "home" | "plans"; workoutId: number; fromJournal?: boolean };

/** Корень: режим платформы и выход живут в контексте (platform/mode.tsx), App ниже — прежнее приложение. */
export function App() {
  return (
    <PlatformProvider signOut={signOutBrowser}>
      <AppInner />
    </PlatformProvider>
  );
}

function AppInner() {
  const setPlatformMode = usePlatformSetter();
  const { mode: platformMode } = usePlatform();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [tab, setTab] = useState<Tab>("home");
  // «+» на Главной → «Записать в журнал» (#263): счётчик запросов, 0 — шторку не открывать.
  const [journalLogRequest, setJournalLogRequest] = useState(0);
  // «Записать» на Workout Detail: тренировка, которой предзаполняется форма записи.
  const [journalLogWorkoutId, setJournalLogWorkoutId] = useState<number | null>(null);
  // «Открыть тренировку» из Журнала (#281): Главная открывается сразу на Workout Detail.
  const [homeWorkoutId, setHomeWorkoutId] = useState<number | null>(null);
  // Откуда открыли «Записать» (#277, D1): «← Назад» из формы возвращает на Workout Detail
  // той вкладки («Главная» / «Планы»), а не в Журнал. После сохранения остаёмся в Журнале.
  const [logOrigin, setLogOrigin] = useState<{ tab: "home" | "plans"; workoutId: number } | null>(null);
  // Из «Записать» вернулись на Workout Detail: его «назад» ведёт на саму вкладку, не в Журнал.
  const [homeWorkoutFromLog, setHomeWorkoutFromLog] = useState(false);
  // Откуда нажали «Начать» на Workout Detail (#277): «Назад» с предэкрана возвращает на деталь, не на вкладку.
  const [startOrigin, setStartOrigin] = useState<WorkoutOrigin | null>(null);
  const [plansWorkoutId, setPlansWorkoutId] = useState<number | null>(null);
  // Откуда ушли в «Открыть тренировку»: Back возвращает в тот же месяц Журнала с той же записью.
  const [journalRestore, setJournalRestore] = useState<JournalRestore | null>(null);
  // Живая тренировка (issue #59) держит несохранённый ввод только во
  // фронтенд-состоянии до финальной отправки (LiveWorkoutScreen.tsx) —
  // переключение вкладок размонтировало бы WorkoutScreen вместе с ней и
  // потеряло бы прогресс молча, поэтому переключение вкладок при активной
  // живой тренировке сначала спрашивает подтверждение.
  const [liveWorkoutActive, setLiveWorkoutActive] = useState(false);
  // Checkpoint 4A (issue #188) — "Начать" на program-backed карточке
  // PlanWeek (DashboardScreen.tsx) ведёт сюда, не в старый WorkoutScreen.
  // Полноэкранный оверлей поверх табов (та же идея, что liveWorkoutActive
  // выше не позволяет молча потерять прогресс) — вместо диалога
  // подтверждения (раздел 15: "не делать большой offline redesign")
  // выход из потока доступен только через собственный onClose экранов
  // (SessionPreScreen.onGoToWorkout на отмену, SessionSummaryScreen.onClose
  // после Complete), не через обычные табы/нижнее меню.
  const [v2Session, setV2Session] = useState<
    | { planItemIds: number[]; manual: boolean; title: string }
    | { workoutId: number; title: string }
    | { resumedSession: LiveSessionResponse }
    | null
  >(null);
  // FAQ (issue #102) открывается и с "Профиля", и сноской у выбора резины
  // на "Тренировке" — запоминаем, откуда пришли, чтобы "Назад" вёл туда же.
  const [faqReturnTab, setFaqReturnTab] = useState<Tab>("profile");
  // Решение 2026-10-17: 402 subscription_required с любого экрана (paywall.ts) — лист «Нужна подписка», затем экран
  // подписки ПОВЕРХ текущей вкладки: вкладка остаётся смонтированной (скрыта), введённое в форму не теряется.
  // Поток тренировки (PlanSessionFlow) показывает свой экран подписки — там лист не нужен.
  const [paywall, setPaywall] = useState<{ phase: "notice"; message: string | null } | { phase: "screen" } | null>(null);
  const v2SessionOpen = useRef(false);
  v2SessionOpen.current = v2Session !== null;
  useEffect(() => subscribeSubscriptionRequired(({ message, openScreen }) => {
    if (v2SessionOpen.current) {
      return;
    }
    setPaywall((current) => (openScreen || current?.phase === "screen" ? { phase: "screen" } : { phase: "notice", message }));
  }), []);

  // Старая живая тренировка (WorkoutScreen) держит ввод только в состоянии экрана — как и новая
  // (SessionLiveScreen), просит подтверждение при закрытии приложения (Bot API 6.2+, #224).
  useClosingConfirmation(liveWorkoutActive);

  function openFaq(from: Tab) {
    setFaqReturnTab(from);
    setTab("faq");
  }

  function handleTabClick(key: Tab) {
    if (key === tab) {
      return;
    }
    const leave = () => {
      setJournalRestore(null);
      setTab(key);
    };
    if (!liveWorkoutActive) {
      leave();
      return;
    }
    // Telegram Web: window.confirm в iframe не показывается и сразу «нет» — нативное подтверждение (confirmAction).
    void confirmAction("Прогресс тренировки будет потерян — уйти?").then((confirmed) => {
      if (confirmed) {
        leave();
      }
    });
  }

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

  // Журнал уже смонтирован с точкой возврата — дальше она не нужна (иначе повторный заход на вкладку восстановил бы устаревшее).
  useEffect(() => {
    if (tab === "journal" && journalRestore !== null) {
      setJournalRestore(null);
    }
  }, [tab, journalRestore]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        // Способ входа определяет platform/authBootstrap.ts (Mini App: initData Telegram; браузер: сессия/вход).
        const auth = await resolveAuth();
        if (auth.kind === "error") {
          throw new Error(auth.message);
        }
        if (auth.kind === "login") {
          if (!cancelled) {
            setState({ status: "login" });
          }
          return;
        }
        const initDataRaw = auth.initDataRaw;
        setPlatformMode(auth.kind === "telegram" ? "telegram" : "browser");
        // #306 B1/F1: недосланные офлайн-события движка v2 (Стоп, пауза, оценка) должны дойти до сервера
        // раньше любого чтения, которое проецирует дедлайны сессии (GET /sessions/live/active, список сессий
        // Журнала): иначе действие пользователя, сделанное до дедлайна, сервер счёл бы устаревшим. Сверка
        // стартует здесь, до первого экрана, и повторяется при временных сбоях; такие чтения ждут её
        // (engineGate.ts). Нет очереди — одно чтение IndexedDB, без сети и без задержки.
        void startEngineReconciliation(initDataRaw);
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

  // Checkpoint 4A (issue #188), раздел 10 — reload/recovery: без этого
  // эффекта перезагрузка страницы посреди STARTED v2-сессии возвращала
  // пользователя на "Главная" с полностью потерянным местом в сессии
  // (найдено живым Playwright-прогоном, не гипотеза) — повторный клик
  // "Начать" породил бы ВТОРУЮ TrainingSession (свежий client_session_id
  // не совпал бы с исходным). Тот же fetchActiveLiveSession, что уже
  // использует SessionV2Lab.tsx — не новый механизм. Проверяется один раз
  // после готовности initDataRaw, не на каждый рендер/смену вкладки.
  useEffect(() => {
    if (state.status !== "ready") {
      return;
    }
    // "not_registered" — строки users ещё нет, а эндпоинты новой схемы
    // отвечают 404 "User not found" на незарегистрированного пользователя:
    // активной сессии у него быть не может, запрос был бы заведомо лишним
    // (и давал 404 в консоли). "Нет активной сессии" у существующего
    // пользователя — обычный 200 {session: null}.
    if (state.data.onboarding_step === "not_registered") {
      return;
    }
    let cancelled = false;
    fetchActiveLiveSession(state.initDataRaw)
      .then((activeSession) => {
        if (!cancelled && activeSession !== null) {
          setV2Session({ resumedSession: activeSession });
        }
      })
      .catch(() => {
        // молчаливо — отсутствие активной сессии (или сетевой сбой этой
        // проверки) не должно блокировать обычную загрузку приложения.
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- запуск ровно
    // один раз на переход в "ready", не на каждое изменение initDataRaw.
  }, [state.status]);

  // #287: с Live-экрана ушли (Back/«Выйти»), пока завершение тренировки ждало сети, — оно лежит в
  // IndexedDB. Вернулась сеть, а экран тренировки не открыт — досылаем отсюда (иначе только при
  // следующем открытии). Пока экран открыт, досылкой владеет он сам (без двойного флаша).
  const liveFlowOpen = v2Session !== null;
  useEffect(() => {
    if (state.status !== "ready" || liveFlowOpen) {
      return;
    }
    const initDataRaw = state.initDataRaw;
    // #306 F1: экран тренировки закрыт (или ещё не открывался) — недосланное его очереди (события, оценка
    // сессии, которую сервер уже завершил сам) сверяет App; идущая сверка просто продолжается.
    void startEngineReconciliation(initDataRaw);
    const onOnline = () => {
      void drainQueuedFinish(initDataRaw);
      void startEngineReconciliation(initDataRaw); // идёт с паузой между повторами — повтор сейчас
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        wakeEngineReconciliation();
      }
    };
    window.addEventListener("online", onOnline);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("online", onOnline);
      document.removeEventListener("visibilitychange", onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initDataRaw неизменен после "ready".
  }, [state.status, liveFlowOpen]);

  // Единицы и тема (#268) — серверные настройки подтягиваются один раз после
  // готовности; до ответа действуют кеш из localStorage / дефолты. Сбой молча.
  useEffect(() => {
    if (state.status !== "ready" || state.data.onboarding_step === "not_registered") {
      return;
    }
    let cancelled = false;
    fetchDisplayPreferences(state.initDataRaw)
      .then((prefs) => {
        if (!cancelled) {
          setDisplayPrefs(prefs);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- один раз на переход в "ready".
  }, [state.status]);

  if (state.status === "loading") {
    return (
      <AppShell withNav={false}>
        <p className="screen-message">Загрузка…</p>
      </AppShell>
    );
  }
  if (state.status === "login") {
    return (
      <AppShell withNav={false}>
        <LoginScreen onSignedIn={() => window.location.reload()} />
      </AppShell>
    );
  }
  if (state.status === "error") {
    return (
      <AppShell withNav={false}>
        <p className="screen-message">
          {isSessionExpiredMessage(state.message) ? state.message : `Не удалось загрузить: ${state.message}`}
        </p>
        {isSessionExpiredMessage(state.message) && (platformMode === "browser" ? (
          // Браузер: сессия потеряна — перезагрузка заново проходит resolveAuth() и показывает вход (WEB-AUTH seam request 2).
          <button type="button" className="action-button" data-testid="session-expired-relogin" onClick={() => window.location.reload()}>
            Войти заново
          </button>
        ) : (
          // initData не обновить изнутри открытого Mini App — только закрыть и открыть из бота (#224).
          <button type="button" className="action-button" data-testid="session-expired-close" onClick={() => getWebApp()?.close?.()}>
            Закрыть
          </button>
        ))}
      </AppShell>
    );
  }

  // Workout Detail нужной вкладки открывается заново; его «назад» ведёт на саму вкладку (не в Журнал).
  // fromJournal (#293): деталь Главной была открыта из Журнала — её «назад» по-прежнему ведёт туда.
  const reopenWorkoutDetail = (origin: WorkoutOrigin) => {
    if (origin.tab === "home") {
      setHomeWorkoutFromLog(!origin.fromJournal);
      setHomeWorkoutId(origin.workoutId);
    } else {
      setPlansWorkoutId(origin.workoutId);
    }
    setTab(origin.tab);
  };

  if (v2Session !== null) {
    return (
      <AppShell withNav={false}>
        <PlanSessionFlow
          initDataRaw={state.initDataRaw}
          planItemIds={"planItemIds" in v2Session ? v2Session.planItemIds : []}
          workoutId={"workoutId" in v2Session ? v2Session.workoutId : undefined}
          manual={"manual" in v2Session ? v2Session.manual : false}
          title={"title" in v2Session ? v2Session.title : (v2Session.resumedSession.title ?? "")}
          initialSession={"resumedSession" in v2Session ? v2Session.resumedSession : null}
          onClose={() => { setV2Session(null); setStartOrigin(null); }}
          onOpenSubscription={() => { setV2Session(null); setStartOrigin(null); setTab("subscription"); }}
          onCancel={() => {
            setV2Session(null);
            const origin = startOrigin;
            setStartOrigin(null);
            if (origin !== null) {
              reopenWorkoutDetail(origin);
            }
          }}
        />
      </AppShell>
    );
  }

  const isOnboarded = state.data.onboarding_step === "done";
  const startWorkout = (workoutId: number, title: string, fromJournal = false) => {
    setStartOrigin(tab === "home" || tab === "plans" ? { tab, workoutId, fromJournal } : null);
    setV2Session({ workoutId, title });
  };
  const logWorkout = (workoutId: number) => {
    setLogOrigin(tab === "home" || tab === "plans" ? { tab, workoutId } : null);
    setJournalRestore(null);
    setJournalLogWorkoutId(workoutId);
    setJournalLogRequest((value) => value + 1);
    setTab("journal");
  };

  const backFromLogToWorkout = () => {
    if (logOrigin === null) {
      return;
    }
    reopenWorkoutDetail(logOrigin);
    setLogOrigin(null);
  };

  // Экспериментальная вкладка новой схемы видна только тестировщикам

  const navTabs = state.data.is_admin ? [...NAV_TABS, DASHBOARD_V2_NAV_TAB] : NAV_TABS;

  return (
    <AppShell withNav={isOnboarded}>
      {isOnboarded && paywall?.phase === "screen" && (
        <SubscriptionScreen initDataRaw={state.initDataRaw} onBack={() => setPaywall(null)} />
      )}
      {isOnboarded && paywall?.phase === "notice" && (
        <SubscriptionRequiredSheet
          message={paywall.message}
          onOpenSubscription={() => setPaywall({ phase: "screen" })}
          onClose={() => setPaywall(null)}
        />
      )}
      <div className="app-tab-host" hidden={isOnboarded && paywall?.phase === "screen"}>
      <p className="app-greeting">Привет, {state.data.name}!</p>
      <EngineStoreBanner />
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
        <HomeScreen
          initDataRaw={state.initDataRaw}
          onOpenPlans={() => setTab("plans")}
          onOpenJournalLog={() => { setJournalRestore(null); setJournalLogWorkoutId(null); setJournalLogRequest((value) => value + 1); setTab("journal"); }}
          onStartWorkout={startWorkout}
          onLogWorkout={logWorkout}
          initialWorkoutId={homeWorkoutId}
          onInitialWorkoutShown={() => { setHomeWorkoutId(null); setHomeWorkoutFromLog(false); }}
          initialWorkoutFromJournal={!homeWorkoutFromLog}
          onExitInitialWorkout={() => setTab("journal")}
        />
      )}
      {isOnboarded && tab === "plans" && (
        <DashboardScreen
          initDataRaw={state.initDataRaw}
          onStartSession={(planItemIds, options) => setV2Session({ planItemIds, ...options })}
          onStartWorkout={startWorkout}
          onLogWorkout={logWorkout}
          initialWorkoutId={plansWorkoutId}
          onInitialWorkoutShown={() => setPlansWorkoutId(null)}
          onOpenHome={() => setTab("home")}
        />
      )}
      {isOnboarded && tab === "workout" && (
        <WorkoutScreen
          initDataRaw={state.initDataRaw}
          onLiveActiveChange={setLiveWorkoutActive}
          onOpenFaq={() => openFaq("workout")}
          onOpenWarmup={() => setTab("warmup")}
        />
      )}
      {isOnboarded && tab === "journal" && <HistoryScreen key={journalLogRequest} initDataRaw={state.initDataRaw} logRequest={journalLogRequest} logWorkoutId={journalLogWorkoutId} restore={journalRestore} onLogBack={logOrigin !== null ? backFromLogToWorkout : undefined} onOpenWorkout={(workoutId, restore) => { setJournalRestore(restore); setHomeWorkoutId(workoutId); setTab("home"); }} />}
      {isOnboarded && tab === "analytics" && <AnalyticsScreen initDataRaw={state.initDataRaw} />}
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
        <SessionV2Lab initDataRaw={state.initDataRaw} onGoToWorkout={() => setTab("workout")} />
      )}

      {isOnboarded && (
        // Навигация (#280): разметка и контракт для e2e (.bottom-tabbar, aria-current) — в platform/NavBar.tsx.
        <NavBar tabs={navTabs} active={tab} onSelect={handleTabClick} />
      )}
      </div>
    </AppShell>
  );
}
