// Чистые помощники типа записи Журнала (#280), без зависимостей — тестируются напрямую.

/** Тип записи Журнала: метка-цвет карточки (plan / freeform / logged / elective / backdated). */
export type JournalKind = "plan" | "freeform" | "logged" | "elective" | "backdated";

export const JOURNAL_KIND_LABELS: Record<JournalKind, string> = {
  plan: "По плану",
  freeform: "Свободная",
  logged: "Активность",
  elective: "Факультатив",
  backdated: "Записана задним числом",
};

export function journalKind(session: { source: string; activity_type?: string | null }): JournalKind {
  if (session.source === "backdated") {
    return "backdated";
  }
  if (session.activity_type != null) {
    return "logged";
  }
  if (session.source === "freeform") {
    return "freeform";
  }
  if (session.source === "elective") {
    return "elective";
  }
  return "plan";
}
