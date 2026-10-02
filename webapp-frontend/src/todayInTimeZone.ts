// «Сегодня» пользователя (#294): сервер проверяет «дата не в будущем» в ЧАСОВОМ ПОЯСЕ ПРОФИЛЯ, поэтому
// дефолты и max= у дат считаются в нём, а не по часам устройства (иначе у UTC+5 при профиле Europe/Moscow
// между 00:00 и 02:00 «Дата не может быть в будущем»). Чистые функции, без React/DOM.

function isValidTimeZone(timeZone: string | null | undefined): timeZone is string {
  if (typeof timeZone !== "string" || timeZone === "") {
    return false;
  }
  try {
    new Intl.DateTimeFormat("en-CA", { timeZone });
    return true;
  } catch {
    return false;
  }
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** Дата устройства YYYY-MM-DD (запасной вариант, когда пояс профиля неизвестен). */
export function deviceToday(now: Date = new Date()): string {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Календарный день YYYY-MM-DD момента `now` в поясе `timeZone` (IANA); пояс неизвестен/невалиден — день устройства. */
export function todayInTimeZone(timeZone: string | null | undefined, now: Date = new Date()): string {
  if (!isValidTimeZone(timeZone)) {
    return deviceToday(now);
  }
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(now);
  const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${pick("year")}-${pick("month")}-${pick("day")}`;
}

/** Момент (ISO UTC) полудня календарного дня `date` в поясе `timeZone` — попадает в этот же день по обе стороны
 * от пояса профиля. Пояс неизвестен — полдень устройства. */
export function noonInTimeZoneIso(date: string, timeZone: string | null | undefined): string {
  const [year, month, day] = date.split("-").map(Number);
  if (!isValidTimeZone(timeZone)) {
    return new Date(year, month - 1, day, 12, 0, 0).toISOString();
  }
  const guess = Date.UTC(year, month - 1, day, 12, 0, 0);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(guess));
  const n = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? "0");
  const asUtc = Date.UTC(n("year"), n("month") - 1, n("day"), n("hour"), n("minute"), n("second"));
  return new Date(guess - (asUtc - guess)).toISOString();
}
