import { formatSecondsAsMinutesSeconds } from "./timeInput.ts";

/**
 * UX-1 — вся логика Builder-конфигурации протокола без React: человеческие
 * названия, состояние формы (draft), сборка protocol dict для backend, валидация
 * и текстовое превью. Превью и summary в списках считаются из ТОГО ЖЕ draft/
 * protocol, что уходит на backend — второго источника правды нет.
 *
 * Backend-контракт (app.domain.workout_protocol.UserWorkoutProtocol) не менялся:
 * reps_sets — один статический target на все подходы, max_effort — попытки + отдых,
 * interval — общее время + работа + отдых (число раундов ВЫВОДИТСЯ, не хранится).
 */

export type ProtocolFormValue = Record<string, unknown>;
export type ProtocolKind = "reps_sets" | "time_sets" | "max_effort" | "interval";

export const PROTOCOL_KINDS: { kind: ProtocolKind; title: string; description: string }[] = [
  { kind: "reps_sets", title: "Повторения", description: "Несколько подходов с заданным количеством повторений" },
  { kind: "time_sets", title: "Время", description: "Несколько подходов на время" },
  { kind: "max_effort", title: "Максимум", description: "Несколько попыток на максимум" },
  { kind: "interval", title: "Интервалы", description: "Работа и отдых по таймеру" },
];

export type ProtocolDraft = {
  kind: ProtocolKind;
  sets: number;
  reps: number;
  durationSeconds: number;
  restSeconds: number;
  attempts: number;
  maxRestSeconds: number;
  totalSeconds: number;
  workSeconds: number;
  intervalRestSeconds: number;
  startsWith: "work" | "rest";
};

export function kindFromProtocol(protocol: ProtocolFormValue | null): ProtocolKind {
  const type = protocol?.type;
  if (type === "reps_sets" || type === "time_sets" || type === "max_effort" || type === "interval") {
    return type;
  }
  return "reps_sets";
}

export function draftFromProtocol(protocol: ProtocolFormValue | null): ProtocolDraft {
  const prescription = (protocol?.prescription ?? {}) as Record<string, unknown>;
  const rest = protocol?.rest_seconds;
  return {
    kind: kindFromProtocol(protocol),
    sets: Number(prescription.sets ?? 3),
    reps: Number(prescription.reps ?? 10),
    durationSeconds: Number(prescription.duration_seconds ?? 30),
    restSeconds: Number(rest ?? 60),
    attempts: Number(prescription.attempts ?? 3),
    maxRestSeconds: Number(rest ?? 180),
    totalSeconds: Number(protocol?.total_duration_seconds ?? 180),
    workSeconds: Number(protocol?.work_seconds ?? 30),
    intervalRestSeconds: Number(rest ?? 30),
    startsWith: protocol?.starts_with === "rest" ? "rest" : "work",
  };
}

/** Русское склонение: plural(3, "подход", "подхода", "подходов"). */
export function plural(n: number, one: string, few: string, many: string): string {
  const mod100 = Math.abs(n) % 100;
  const mod10 = mod100 % 10;
  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

/** Человеческое время: 0:30 → «30 сек», 1:00 → «1:00», 0 → «без отдыха» решает вызывающий. */
export function humanDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} сек`;
  return formatSecondsAsMinutesSeconds(total).replace(/^0/, "");
}

/** Число рабочих фаз, которое поместится в общее время. Формула та же, что
 * app/domain/interval_timing.py::calculate_completed_cycles (без «≈»). */
export function intervalRounds(totalSeconds: number, workSeconds: number, restSeconds: number): number {
  if (workSeconds <= 0 || totalSeconds < workSeconds) return 0;
  const cycle = workSeconds + restSeconds;
  if (cycle <= 0) return 0;
  return Math.floor((totalSeconds - workSeconds) / cycle) + 1;
}

export type BuildResult = { ok: true; protocol: ProtocolFormValue } | { ok: false; error: string };

export function buildProtocol(d: ProtocolDraft): BuildResult {
  const err = (error: string): BuildResult => ({ ok: false, error });
  const whole = (n: number) => Number.isInteger(n);
  if (d.kind === "reps_sets") {
    if (!(d.sets > 0) || !whole(d.sets)) return err("Укажите количество подходов");
    if (!(d.reps > 0) || !whole(d.reps)) return err("Укажите число повторений в подходе");
    if (d.restSeconds < 0) return err("Отдых не может быть отрицательным");
    return {
      ok: true,
      protocol: { type: "reps_sets", prescription: { source: "static", sets: d.sets, reps: d.reps }, rest_seconds: d.restSeconds },
    };
  }
  if (d.kind === "time_sets") {
    if (!(d.sets > 0) || !whole(d.sets)) return err("Укажите количество подходов");
    if (!(d.durationSeconds > 0)) return err("Укажите длительность подхода");
    if (d.restSeconds < 0) return err("Отдых не может быть отрицательным");
    return {
      ok: true,
      protocol: {
        type: "time_sets",
        prescription: { source: "static", sets: d.sets, duration_seconds: d.durationSeconds },
        rest_seconds: d.restSeconds,
      },
    };
  }
  if (d.kind === "max_effort") {
    if (!(d.attempts > 0) || !whole(d.attempts)) return err("Укажите количество попыток");
    if (d.maxRestSeconds < 0) return err("Отдых не может быть отрицательным");
    return {
      ok: true,
      protocol: { type: "max_effort", prescription: { source: "static", attempts: d.attempts }, rest_seconds: d.maxRestSeconds },
    };
  }
  if (!(d.totalSeconds > 0)) return err("Укажите общее время");
  if (!(d.workSeconds > 0)) return err("Укажите длительность работы");
  if (d.intervalRestSeconds < 0) return err("Отдых не может быть отрицательным");
  if (d.workSeconds > d.totalSeconds) return err("Работа не может быть длиннее общего времени");
  return {
    ok: true,
    protocol: {
      type: "interval",
      total_duration_seconds: d.totalSeconds,
      work_seconds: d.workSeconds,
      rest_seconds: d.intervalRestSeconds,
      starts_with: d.startsWith,
    },
  };
}

/** Превью «что будет в тренировке»: [главная строка, уточнение]. */
export function previewLines(d: ProtocolDraft): [string, string] {
  if (d.kind === "reps_sets") {
    return [
      `${d.sets} × ${d.reps} ${plural(d.reps, "повторение", "повторения", "повторений")}`,
      d.restSeconds > 0 ? `Отдых между подходами ${humanDuration(d.restSeconds)}` : "Без отдыха между подходами",
    ];
  }
  if (d.kind === "time_sets") {
    return [
      `${d.sets} × ${humanDuration(d.durationSeconds)}`,
      d.restSeconds > 0 ? `Отдых между подходами ${humanDuration(d.restSeconds)}` : "Без отдыха между подходами",
    ];
  }
  if (d.kind === "max_effort") {
    return [
      `${d.attempts} ${plural(d.attempts, "попытка", "попытки", "попыток")} на максимум`,
      d.maxRestSeconds > 0 ? `Отдых между попытками ${humanDuration(d.maxRestSeconds)}` : "Без отдыха между попытками",
    ];
  }
  const rounds = intervalRounds(d.totalSeconds, d.workSeconds, d.intervalRestSeconds);
  const first = `${rounds} ${plural(rounds, "раунд", "раунда", "раундов")}`;
  const rest = d.intervalRestSeconds > 0 ? `${humanDuration(d.intervalRestSeconds)} отдых` : "без отдыха";
  return [first, `${humanDuration(d.workSeconds)} работа / ${rest} · всего ${humanDuration(d.totalSeconds)}`];
}

/** Строка для карточки упражнения в списке (тот же previewLines). */
export function summarizeProtocol(protocol: ProtocolFormValue): { kindTitle: string; lines: [string, string] } {
  const draft = draftFromProtocol(protocol);
  const known = protocol.type === draft.kind;
  return {
    kindTitle: known ? (PROTOCOL_KINDS.find((k) => k.kind === draft.kind)?.title ?? "Тренировка") : "Тренировка",
    lines: previewLines(draft),
  };
}
