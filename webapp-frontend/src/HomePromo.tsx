/** Promo-баннеры между секциями Главной (#280): крупный тональный блок с одним действием.
 * Доступное имя — отдельное «Баннер: …» (aria-label), видимый текст не повторяет названия кнопок
 * «Создать тренировку» / «Записать» / «Начать» — иначе дубли имён ломают строгие селекторы E2E. */
export type PromoKind = "plan" | "log" | "create";

const PROMOS: Record<PromoKind, { title: string; meta: string; label: string; testId: string; icon: string }> = {
  plan: {
    title: "Готовы заниматься?", meta: "Откройте план дня", label: "Баннер: открыть план дня",
    testId: "home-promo-plan", icon: "M4.5 5.5h15v14h-15zM4.5 10h15M8.5 3.5v4M15.5 3.5v4",
  },
  log: {
    title: "Занимались вне приложения?", meta: "Добавьте активность в историю", label: "Баннер: внести активность",
    testId: "home-promo-log", icon: "M12 4v16M4 12h16",
  },
  create: {
    title: "Своя программа", meta: "Соберите комплекс из упражнений и протоколов", label: "Баннер: собрать свой комплекс",
    testId: "home-promo-create", icon: "M3.5 9.5v5M6.5 7v10M17.5 7v10M20.5 9.5v5M6.5 12h11",
  },
};

export function HomePromo({ kind, onClick }: { kind: PromoKind; onClick: () => void }) {
  const promo = PROMOS[kind];
  return (
    <button type="button" className="home-promo" data-promo={kind} data-testid={promo.testId} aria-label={promo.label} onClick={onClick}>
      <span className="home-promo-text">
        <span className="home-promo-title">{promo.title}</span>
        <span className="home-promo-meta">{promo.meta}</span>
      </span>
      <span className="home-promo-icon" aria-hidden="true">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" focusable="false">
          <path d={promo.icon} />
        </svg>
      </span>
    </button>
  );
}
