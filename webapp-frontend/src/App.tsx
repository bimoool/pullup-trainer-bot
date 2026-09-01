import { retrieveLaunchParams } from "@telegram-apps/sdk";
import { useEffect, useState } from "react";

import { fetchHello, type HelloResponse } from "./api";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: HelloResponse };

export function App() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

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
        try {
          initDataRaw = retrieveLaunchParams().initDataRaw;
        } catch {
          initDataRaw = undefined;
        }
        if (!initDataRaw) {
          initDataRaw = (window as unknown as { Telegram?: { WebApp?: { initData?: string } } }).Telegram?.WebApp
            ?.initData;
        }
        if (!initDataRaw) {
          throw new Error("initDataRaw is empty — открыто не из Telegram?");
        }
        const data = await fetchHello(initDataRaw);
        if (!cancelled) {
          setState({ status: "ready", data });
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
    return <p>Загрузка…</p>;
  }
  if (state.status === "error") {
    return <p>Не удалось загрузить: {state.message}</p>;
  }

  return (
    <div>
      <h1>Привет, {state.data.name}!</h1>
      {!state.data.is_onboarded && <p>Онбординг ещё не пройден.</p>}
      {state.data.readiness_status && (
        <p>
          Статус готовности: {state.data.readiness_status} (дней с последней тренировки:{" "}
          {state.data.days_since_last_workout})
        </p>
      )}
    </div>
  );
}
