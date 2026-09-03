import { init } from "@telegram-apps/sdk";
import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { ErrorBoundary } from "./ErrorBoundary";
import "./index.css";

// issue #34: window.Telegram.WebApp — тот же мост, что App.tsx уже использует
// как надёжный запасной источник initData (issue #23) — читаем напрямую, не
// через SDK, чтобы не зависеть от его mount()/isAvailable() на окружениях,
// где сам init() ниже уже падал на мобильном (issue #24). Значения из
// themeParams перекрывают light-дефолты из src/index.css CSS-переменными,
// так что фон и цвет текста остаются согласованной парой, а не двумя
// независимыми дефолтами, которые могут разъехаться (см. issue #34).
// issue #38: то же перекрытие CSS-переменных, что issue #34 завёл для
// bg/text/hint, — теперь ещё и для палитры, нужной полноценной стилизации
// (кнопка, карточки блоков, подписи). Каждая переменная опциональна и
// падает на light-дефолт из src/index.css, если конкретное поле темы
// клиент не прислал (themeParams — не гарантированно полный набор).
const THEME_PARAM_TO_CSS_VAR: Record<string, string> = {
  bg_color: "--tg-bg-color",
  text_color: "--tg-text-color",
  hint_color: "--tg-hint-color",
  link_color: "--tg-link-color",
  button_color: "--tg-button-color",
  button_text_color: "--tg-button-text-color",
  secondary_bg_color: "--tg-secondary-bg-color",
  section_bg_color: "--tg-section-bg-color",
  subtitle_text_color: "--tg-subtitle-text-color",
  destructive_text_color: "--tg-destructive-text-color",
};

function applyTelegramTheme() {
  const themeParams = (window as unknown as { Telegram?: { WebApp?: { themeParams?: Record<string, string> } } })
    .Telegram?.WebApp?.themeParams;
  if (!themeParams) {
    return;
  }
  const root = document.documentElement.style;
  for (const [param, cssVar] of Object.entries(THEME_PARAM_TO_CSS_VAR)) {
    if (themeParams[param]) {
      root.setProperty(cssVar, themeParams[param]);
    }
  }
}
applyTelegramTheme();

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
