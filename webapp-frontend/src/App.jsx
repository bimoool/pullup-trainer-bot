import { useEffect, useState } from "react";

// Минимальный экран Этапа 0 — доказывает цепочку бот → кнопка → mini app →
// HTTPS → бэкенд → domain-логику (см. app/web/main.py::hello), не более.
export default function App() {
  const [state, setState] = useState({ loading: true, error: null, data: null });

  useEffect(() => {
    const tg = window.Telegram?.WebApp;
    tg?.ready();
    tg?.expand();

    const initData = tg?.initData;
    if (!initData) {
      setState({
        loading: false,
        error: "Открой эту страницу кнопкой в боте — initData доступна только внутри Telegram.",
        data: null,
      });
      return;
    }

    fetch("/api/hello", { headers: { Authorization: `tma ${initData}` } })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => setState({ loading: false, error: null, data }))
      .catch((err) => setState({ loading: false, error: err.message, data: null }));
  }, []);

  if (state.loading) return <p>Загрузка…</p>;
  if (state.error) return <p>Ошибка: {state.error}</p>;

  return (
    <div style={{ fontFamily: "sans-serif", padding: 16 }}>
      <h1>{state.data.greeting}</h1>
      {state.data.readiness && <p>{state.data.readiness}</p>}
    </div>
  );
}
