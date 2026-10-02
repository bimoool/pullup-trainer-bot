import type { ReactNode } from "react";

import { Icon, type IconName } from "./Icon";

/** Grouped-list примитивы Профиля (#280): группа = подпись + одна карточка со строками-разделителями;
 * строка = иконка-бейдж, подпись, значение справа, шеврон у переходов. Только разметка, поведение у вызывающего. */

export function RowIcon({ name }: { name: IconName | string }) {
  return (
    <span className="profile-row-icon" aria-hidden="true">
      <Icon name={name} />
    </span>
  );
}

function Chevron() {
  return <Icon name="chevronRight" size={16} strokeWidth={2.2} className="profile-row-chevron" />;
}

type GroupProps = {
  title: string;
  testId?: string;
  children: ReactNode;
  note?: ReactNode;
  /** Блок между подписью группы и карточкой строк (крупные показатели). */
  lead?: ReactNode;
};

export function ProfileGroup({ title, testId, children, note, lead }: GroupProps) {
  return (
    <section className="profile-section" data-testid={testId}>
      <p className="profile-group-label">{title}</p>
      {lead}
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

/** Крупный показатель (вес/рост, #286 C2): акцентное число над подписью, шеврон справа.
 * В DOM порядок «подпись, значение» — textContent «Вес: 75 кг», визуально значение над подписью. */
export function ProfileMetric({ label, value, onClick, ariaLabel, testId }: {
  label: string; value: string; onClick: () => void; ariaLabel?: string; testId?: string;
}) {
  const match = /^(-?[\d.,]+)\s*(.*)$/.exec(value);
  return (
    <button type="button" className="profile-metric" aria-label={ariaLabel} data-testid={testId} onClick={onClick}>
      <span className="profile-metric-text">
        <span className="profile-metric-label">{label}</span>
        <span className="profile-row-sep">: </span>
        <span className="profile-metric-value">
          {match === null ? (
            <span className="profile-metric-empty">{value}</span>
          ) : (
            <>
              <span className="profile-metric-number">{match[1]}</span>
              {match[2] !== "" && <> <span className="profile-metric-unit">{match[2]}</span></>}
            </>
          )}
        </span>
      </span>
      <Chevron />
    </button>
  );
}
