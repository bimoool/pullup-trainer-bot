import type { ReactElement } from "react";

import { categoryGlyphKey, type GlyphKey } from "./categoryGlyphKey";

/** Контурные глифы 24×24 (stroke = currentColor); декоративные — aria-hidden. */
const GLYPHS: Record<GlyphKey, ReactElement> = {
  dumbbell: <path d="M3.5 9.5v5M6.5 7v10M17.5 7v10M20.5 9.5v5M6.5 12h11" />,
  pulse: <path d="M3 12h4l2.5-6 4 12 2.5-6h5" />,
  target: (<><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3.5" /></>),
  bolt: <path d="M13 3 5.5 13.5H11L10 21l7.5-10.5H12z" />,
  figure: (<><circle cx="12" cy="5.5" r="2.3" /><path d="M12 8.5v6M6.5 10.5 12 8.5l5.5 2M9.5 21l2.5-6.5 2.5 6.5" /></>),
  flame: <path d="M12 3c.8 3.6 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3.2 2-4 0 2 .8 3 2 3 1.2-3 0-6 1-9z" />,
  hang: (<><path d="M3.5 5h17" /><circle cx="12" cy="10" r="2" /><path d="M8.5 5v4M15.5 5v4M12 12v4.5M9.5 20.5l2.5-4 2.5 4" /></>),
  wave: <path d="M3 14c2.5-6 4.5 6 9 0s6.5 6 9 0" />,
};

export function CategoryGlyph({ category, index = 0, size = 18, glyph }: {
  category?: string; index?: number; size?: number; glyph?: GlyphKey;
}) {
  const key = glyph ?? categoryGlyphKey(category ?? "", index);
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {GLYPHS[key]}
    </svg>
  );
}
