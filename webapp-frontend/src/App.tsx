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
        const { initDataRaw } = retrieveLaunchParams();
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
