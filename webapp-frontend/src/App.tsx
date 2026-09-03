import { retrieveLaunchParams } from "@telegram-apps/sdk";
import { Tabbar } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchHello, type HelloResponse } from "./api";
import { ProfileScreen } from "./ProfileScreen";
import { WorkoutScreen } from "./WorkoutScreen";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: HelloResponse; initDataRaw: string };

/** Базовая навигация (issue #45, часть 3) — задел под структуру, не
 * перенос всего функционала бота: пока два раздела, третий добавляется
 * так же, одной записью в NAV_TABS + веткой в рендере ниже. */
type Tab = "workout" | "profile";

const NAV_TABS: { key: Tab; icon: string; label: string }[] = [
  { key: "workout", icon: "💪", label: "Тренировка" },
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
      {state.data.is_onboarded && tab === "workout" && <WorkoutScreen initDataRaw={state.initDataRaw} />}
      {state.data.is_onboarded && tab === "profile" && <ProfileScreen initDataRaw={state.initDataRaw} />}

      {state.data.is_onboarded && (
        <Tabbar>
          {NAV_TABS.map(({ key, icon, label }) => (
            <Tabbar.Item key={key} text={label} selected={tab === key} onClick={() => setTab(key)}>
              <span className="bottom-nav-icon">{icon}</span>
            </Tabbar.Item>
          ))}
        </Tabbar>
      )}
    </div>
  );
}
