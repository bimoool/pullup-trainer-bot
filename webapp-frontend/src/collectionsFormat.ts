import { plural } from "./blockFormat.ts";

/** Подпись состава подборки на карточке и в шапке: «3 программы», «2 упражнения»,
 * для смешанного состава — «5 элементов». Считает только реально видимые элементы. */
export function formatCollectionCount(counts: {
  items_count: number; programs_count: number; exercises_count: number;
}): string {
  const { items_count: total, programs_count: programs, exercises_count: exercises } = counts;
  if (programs === total && programs > 0) {
    return `${programs} ${plural(programs, "программа", "программы", "программ")}`;
  }
  if (exercises === total && exercises > 0) {
    return `${exercises} ${plural(exercises, "упражнение", "упражнения", "упражнений")}`;
  }
  return `${total} ${plural(total, "элемент", "элемента", "элементов")}`;
}

/** Подпись типа элемента в списке подборки. */
export function collectionItemKindLabel(itemType: "program" | "exercise"): string {
  return itemType === "program" ? "Программа" : "Упражнение";
}
