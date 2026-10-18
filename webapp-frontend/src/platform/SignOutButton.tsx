// Кнопка «Выйти» для браузерного режима (WEB-AUTH). Рендерится только когда есть signOut (то есть режим browser):
// в Mini App внутри Telegram выходить не из чего, кнопки нет. Размещает её координатор (seam-запрос WEB-AUTH).
import "./login.css";
import { usePlatform } from "./mode";

export function SignOutButton({ className }: { className?: string }) {
  const { signOut } = usePlatform();
  if (!signOut) {
    return null;
  }
  return (
    <button type="button" className={className ?? "login-link-button"} data-testid="sign-out" onClick={signOut}>
      Выйти из аккаунта
    </button>
  );
}
