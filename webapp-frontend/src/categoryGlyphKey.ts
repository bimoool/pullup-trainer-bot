/** Глиф бейджа категории (Главная, Workout Detail): подбирается по названию категории, иначе —
 * по порядку ряда. Чистая логика без разметки — разметка в CategoryGlyph.tsx. */
export type GlyphKey = "dumbbell" | "pulse" | "target" | "bolt" | "figure" | "flame" | "hang" | "wave";

const ORDER: GlyphKey[] = ["dumbbell", "pulse", "target", "bolt", "figure", "flame"];

const RULES: [RegExp, GlyphKey][] = [
  [/подтяг|вис|hang|pull|хват|гриф/i, "hang"],
  [/сил|мощ|power|strength/i, "dumbbell"],
  [/вынослив|кардио|aerob|endur|бег|интервал/i, "pulse"],
  [/гибк|растяж|mobil|flex|йог|разминк/i, "wave"],
  [/кор|пресс|core|баланс/i, "target"],
  [/офп|общ|физ|condition|general/i, "figure"],
];

export function categoryGlyphKey(category: string, index: number): GlyphKey {
  const name = category.trim();
  for (const [pattern, key] of RULES) {
    if (pattern.test(name)) {
      return key;
    }
  }
  return ORDER[((index % ORDER.length) + ORDER.length) % ORDER.length];
}
