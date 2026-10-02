import type { ReactNode } from "react";

/** Набор контурных SVG-иконок (#286 C): замена эмодзи в роли иконок кнопок/заголовков.
 * Стиль как у NavIcon: сетка 24, штрих currentColor, скруглённые концы. Иконка всегда декоративна
 * (aria-hidden) — доступное имя кнопки задаёт её ТЕКСТ или aria-label, поэтому подписи не меняются. */
export const ICON_PATHS = {
  weight: <><path d="M6 8h12l1.6 11H4.4L6 8Z" /><circle cx="12" cy="5.2" r="2" /></>,
  height: <path d="M12 3v18M8.5 6.5 12 3l3.5 3.5M8.5 17.5 12 21l3.5-3.5" />,
  person: <><circle cx="12" cy="8" r="3.4" /><path d="M5 20c.6-3.7 3.4-5.6 7-5.6s6.4 1.9 7 5.6" /></>,
  calendar: <><rect x="4" y="5" width="16" height="15" rx="2.5" /><path d="M4 10h16M8.5 3v4M15.5 3v4" /></>,
  clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>,
  edit: <><path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4Z" /><path d="m13.5 6.5 4 4" /></>,
  star: <path d="m12 3.6 2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.8l-5.2 2.8 1-5.8-4.2-4.1 5.8-.8L12 3.6Z" />,
  help: <><circle cx="12" cy="12" r="8.5" /><path d="M9.6 9.4a2.5 2.5 0 1 1 3.6 2.2c-.8.4-1.2.9-1.2 1.8M12 16.9v.1" /></>,
  band: <path d="M5 9c0-2 2-3.5 4.5-3.5h5C17 5.5 19 7 19 9s-2 3.5-4.5 3.5h-5C7 12.5 5 14 5 16s2 3.5 4.5 3.5h5" />,
  test: <><path d="M6 4.5h12v15H6z" /><path d="M9 9h6M9 12.5h6M9 16h3" /></>,
  settings: <>
    <path d="M10.3 4.3c.4-1.8 2.9-1.8 3.4 0a1.7 1.7 0 0 0 2.5 1.1c1.5-.9 3.3.8 2.4 2.4a1.7 1.7 0 0 0 1.1 2.5c1.8.4 1.8 2.9 0 3.4a1.7 1.7 0 0 0-1.1 2.5c.9 1.5-.8 3.3-2.4 2.4a1.7 1.7 0 0 0-2.5 1.1c-.4 1.8-2.9 1.8-3.4 0a1.7 1.7 0 0 0-2.5-1.1c-1.5.9-3.3-.8-2.4-2.4a1.7 1.7 0 0 0-1.1-2.5c-1.8-.4-1.8-2.9 0-3.4a1.7 1.7 0 0 0 1.1-2.5c-.9-1.5.8-3.3 2.4-2.4 1 .6 2.3.1 2.5-1.1Z" />
    <circle cx="12" cy="12" r="3" />
  </>,
  trash: <><path d="M4.5 7h15M9.5 7V4.8h5V7M6.5 7l.8 12.2h9.4L17.5 7" /><path d="M10 11v5.5M14 11v5.5" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  checkCircle: <><circle cx="12" cy="12" r="8.5" /><path d="m8.2 12.3 2.6 2.6 5-5.4" /></>,
  circle: <circle cx="12" cy="12" r="8.5" />,
  chart: <><path d="M4 19.5h16" /><path d="m5.5 15 4-4.5 3 3 5.5-6.5" /></>,
  trophy: <><path d="M8 4.5h8v5a4 4 0 0 1-8 0v-5Z" /><path d="M8 6.5H5.2c0 2.6 1 4 2.9 4.3M16 6.5h2.8c0 2.6-1 4-2.9 4.3M12 13.5v3.2M8.5 19.5h7M9.5 16.7h5" /></>,
  medal: <><circle cx="12" cy="14.5" r="4.6" /><path d="m8.6 11.4-2.4-7.4h4l1.8 4M15.4 11.4l2.4-7.4h-4L12 8" /></>,
  file: <><path d="M6.5 3.8h7l4 4v12.4h-11z" /><path d="M13.5 3.8v4h4M9 12.5h6M9 16h6" /></>,
  card: <><rect x="3.5" y="6" width="17" height="12" rx="2.5" /><path d="M3.5 10.2h17M7 14.8h3" /></>,
  flame: <path d="M12 3.5c.5 3-2.8 4.6-3.6 7.4A5 5 0 0 0 12 20a5 5 0 0 0 4.6-6.6c-.4-1-1.2-1.8-1.8-2.6-.3 1-.8 1.6-1.6 1.9.5-2.6-.2-5.9-1.2-8.2Z" />,
  target: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.6" /><circle cx="12" cy="12" r=".8" /></>,
  repeat: <><path d="M5 11V9.5A2.5 2.5 0 0 1 7.5 7H18M15 4l3 3-3 3" /><path d="M19 13v1.5a2.5 2.5 0 0 1-2.5 2.5H6M9 20l-3-3 3-3" /></>,
  timer: <><circle cx="12" cy="13.5" r="6.5" /><path d="M12 10.5v3l2 1.5M9.5 3.5h5M12 3.5v3.5" /></>,
  note: <><path d="M5 19.5V5.5a1.5 1.5 0 0 1 1.5-1.5h11A1.5 1.5 0 0 1 19 5.5v9L14 19.5H6.5A1.5 1.5 0 0 1 5 18Z" /><path d="M14 19.5v-4a1 1 0 0 1 1-1h4M8.5 9h7M8.5 12h4" /></>,
  volumeUp: <><path d="M4.5 9.8h3l4-3.3v11l-4-3.3h-3z" /><path d="M15 9.2a4 4 0 0 1 0 5.6M17.4 6.8a7.4 7.4 0 0 1 0 10.4" /></>,
  volumeDown: <><path d="M4.5 9.8h3l4-3.3v11l-4-3.3h-3z" /><path d="M15 9.2a4 4 0 0 1 0 5.6" /></>,
  chevronRight: <path d="m9 5 7 7-7 7" />,
  chevronDown: <path d="m5 9 7 7 7-7" />,
  chevronUp: <path d="m5 15 7-7 7 7" />,
  heart: <path d="M12 20.5s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7.6a4.3 4.3 0 0 1 7.5 2.7c0 5.6-7.5 10.2-7.5 10.2z" />,
  download: <path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14" />,
  info: <><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.2M12 7.9v.1" /></>,
  play: <path d="M8 5.5v13l10.5-6.5L8 5.5Z" />,
  weightlift: <><path d="M3.5 10v4M6.5 8v8M17.5 8v8M20.5 10v4M6.5 12h11" /></>,
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof ICON_PATHS;

type Props = { name: IconName | string; size?: number; strokeWidth?: number; className?: string; /** Залить фигуру цветом текста (активное сердечко). */ filled?: boolean };

/** Декоративная SVG-иконка: `aria-hidden`, цвет = currentColor. Неизвестное имя рисует «person». */
export function Icon({ name, size = 18, strokeWidth = 1.9, className, filled = false }: Props) {
  const paths = (ICON_PATHS as Record<string, ReactNode>)[name] ?? ICON_PATHS.person;
  return (
    <svg
      className={className === undefined ? "vp-icon" : `vp-icon ${className}`}
      width={size} height={size} viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} stroke="currentColor"
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"
    >
      {paths}
    </svg>
  );
}
