/** Иконки нижней навигации (#280): контурные 24 px, цвет — currentColor (задаёт shell.css).
 * Свои SVG, не эмодзи: единый вес линии и аккуратная окраска активной вкладки. */
type Props = { name: string; active?: boolean };

export function NavIcon({ name, active = false }: Props) {
  const common = {
    width: 24, height: 24, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    strokeWidth: active ? 2 : 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
    "aria-hidden": true, focusable: false, className: "bottom-tabbar-icon",
  };
  switch (name) {
    case "home":
      return (
        <svg {...common}>
          <path d="M3.5 11 12 3.8 20.5 11" />
          <path d="M5.5 9.7V20h13V9.7" />
          <path d="M9.8 20v-5.6h4.4V20" />
        </svg>
      );
    case "plans":
      return (
        <svg {...common}>
          <rect x="4" y="4.5" width="16" height="16" rx="2.5" />
          <path d="M4 9.5h16M8.5 2.8v3.4M15.5 2.8v3.4" />
          <path d="M8.5 13.5h3M8.5 16.8h6" />
        </svg>
      );
    case "journal":
      return (
        <svg {...common}>
          <path d="M12 6.2C10.4 5 8 4.6 4 4.6v13.8c4 0 6.4.4 8 1.6 1.6-1.2 4-1.6 8-1.6V4.6c-4 0-6.4.4-8 1.6Z" />
          <path d="M12 6.2V20" />
        </svg>
      );
    case "analytics":
      return (
        <svg {...common}>
          <rect x="4.5" y="12" width="3.4" height="7.5" rx="1" />
          <rect x="10.3" y="4.5" width="3.4" height="15" rx="1" />
          <rect x="16.1" y="9" width="3.4" height="10.5" rx="1" />
        </svg>
      );
    case "profile":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <circle cx="12" cy="9.8" r="3" />
          <path d="M6.3 18.2c1.3-2.3 3.2-3.4 5.7-3.4s4.4 1.1 5.7 3.4" />
        </svg>
      );
    default:
      // dashboardV2 (лаборатория, только админы): колба.
      return (
        <svg {...common}>
          <path d="M9.5 3.5h5M10.5 3.5v5.2L5.6 17a2.2 2.2 0 0 0 1.9 3.3h9a2.2 2.2 0 0 0 1.9-3.3l-4.9-8.3V3.5" />
        </svg>
      );
  }
}
