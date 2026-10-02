import type { ReactNode } from "react";

/** Grouped-list примитивы Профиля (#280): группа = подпись + одна карточка со строками-разделителями;
 * строка = иконка-бейдж, подпись, значение справа, шеврон у переходов. Только разметка, поведение у вызывающего. */

const ICONS: Record<string, ReactNode> = {
  weight: <><path d="M6 8h12l1.6 11H4.4L6 8Z" /><circle cx="12" cy="5.2" r="2" /></>,
  height: <><path d="M12 3v18M8.5 6.5 12 3l3.5 3.5M8.5 17.5 12 21l3.5-3.5" /></>,
  person: <><circle cx="12" cy="8" r="3.4" /><path d="M5 20c.6-3.7 3.4-5.6 7-5.6s6.4 1.9 7 5.6" /></>,
  calendar: <><rect x="4" y="5" width="16" height="15" rx="2.5" /><path d="M4 10h16M8.5 3v4M15.5 3v4" /></>,
  clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>,
  edit: <><path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4Z" /><path d="m13.5 6.5 4 4" /></>,
  star: <path d="m12 3.6 2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.8l-5.2 2.8 1-5.8-4.2-4.1 5.8-.8L12 3.6Z" />,
  help: <><circle cx="12" cy="12" r="8.5" /><path d="M9.6 9.4a2.5 2.5 0 1 1 3.6 2.2c-.8.4-1.2.9-1.2 1.8M12 16.9v.1" /></>,
  band: <><path d="M5 9c0-2 2-3.5 4.5-3.5h5C17 5.5 19 7 19 9s-2 3.5-4.5 3.5h-5C7 12.5 5 14 5 16s2 3.5 4.5 3.5h5" /></>,
  test: <><path d="M6 4.5h12v15H6z" /><path d="M9 9h6M9 12.5h6M9 16h3" /></>,
};

export function RowIcon({ name }: { name: keyof typeof ICONS | string }) {
  return (
    <span className="profile-row-icon" aria-hidden="true">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" focusable="false">
        {ICONS[name] ?? ICONS.person}
      </svg>
    </span>
  );
}

function Chevron() {
  return (
    <svg className="profile-row-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="m9 5 7 7-7 7" />
    </svg>
  );
}

export function ProfileGroup({ title, testId, children, note }: { title: string; testId?: string; children: ReactNode; note?: ReactNode }) {
  return (
    <section className="profile-section" data-testid={testId}>
      <p className="profile-group-label">{title}</p>
      <div className="profile-group">{children}</div>
      {note}
    </section>
  );
}

type RowProps = {
  icon: string;
  label: string;
  /** Значение справа; в textContent строки склеивается как «подпись: значение». */
  value?: string;
  onClick?: () => void;
  ariaLabel?: string;
  testId?: string;
  /** Длинное значение — вторая строка под подписью, а не справа. */
  stacked?: boolean;
};

/** Строка группы: с onClick — настоящая кнопка с шевроном, иначе статическая строка. */
export function ProfileRow({ icon, label, value, onClick, ariaLabel, testId, stacked = false }: RowProps) {
  const inner = (
    <>
      <RowIcon name={icon} />
      <span className="profile-row-text">
        <span className="profile-row-label">{label}</span>
        {value !== undefined && (
          <>
            <span className="profile-row-sep">: </span>
            <span className="profile-row-value">{value}</span>
          </>
        )}
      </span>
      {onClick && <Chevron />}
    </>
  );
  if (onClick) {
    return (
      <button type="button" className={stacked ? "profile-row profile-row-link profile-row-stacked" : "profile-row profile-row-link"} aria-label={ariaLabel} data-testid={testId} onClick={onClick}>
        {inner}
      </button>
    );
  }
  return <div className={stacked ? "profile-row profile-row-stacked" : "profile-row"} data-testid={testId}>{inner}</div>;
}
