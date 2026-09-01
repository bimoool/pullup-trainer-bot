import { init } from "@telegram-apps/sdk";
import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { ErrorBoundary } from "./ErrorBoundary";

try {
  // Issue #24: на мобильном Telegram init() (внутри себя дёргает
  // retrieveLaunchParams(), тот же путь, что и "initDataRaw is empty" из
  // #23) бросал исключение прямо здесь — на верхнем уровне модуля, до
  // ReactDOM.render. Без try/catch это ронялось необработанным
  // исключением до рендера даже <p>Загрузка…</p> — чёрный экран без
  // единого сообщения. На Desktop до этой строки, видимо, доходит
  // успешно, а ошибка ловится уже внутри App.tsx.
  init();
} catch (error) {
  console.error("Telegram SDK init() failed", error);
}

const rootElement = document.getElementById("root")!;

try {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>,
  );
} catch (error) {
  console.error("Failed to render Mini App", error);
  rootElement.innerHTML = "<p>Что-то пошло не так, попробуй ещё раз.</p>";
}
