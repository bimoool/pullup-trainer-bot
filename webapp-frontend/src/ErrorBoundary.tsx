import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

/**
 * Issue #24: на мобильном Telegram необработанное исключение при рендере
 * давало полностью чёрный экран без единого сообщения — на Desktop то же
 * исключение почему-то не долетало до пользователя. Эта граница — общая
 * страховка на верхнем уровне: любая ошибка рендера/эффекта ниже по дереву
 * должна показывать текст, а не пустой экран.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Mini App crashed", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 16, fontFamily: "sans-serif" }}>
          <p>Что-то пошло не так, попробуй ещё раз.</p>
          <p style={{ color: "#888", fontSize: 12 }}>{this.state.error.message}</p>
        </div>
      );
    }
    return this.props.children;
  }
}
