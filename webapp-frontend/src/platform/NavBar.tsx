// Навигация. Владелец — WEB-LAYOUT (до его работы — прежняя нижняя панель Mini App, #280).
// Контракт e2e: контейнер .bottom-tabbar, внутри <button> с подписью-<span> прямым потомком; aria-current="page" у активной.
import { NavIcon } from "../NavIcon";

export type NavTab = { key: string; label: string };

export function NavBar({ tabs, active, onSelect }: { tabs: NavTab[]; active: string; onSelect: (key: never) => void }) {
  return (
    <nav className="bottom-tabbar" aria-label="Основная навигация">
      {tabs.map(({ key, label }) => (
        <button
          key={key}
          type="button"
          className={active === key ? "bottom-tabbar-item bottom-tabbar-item-active" : "bottom-tabbar-item"}
          aria-current={active === key ? "page" : undefined}
          onClick={() => (onSelect as (key: string) => void)(key)}
        >
          <NavIcon name={key} active={active === key} />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}
