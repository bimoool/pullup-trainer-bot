// Время записей Журнала в часовом поясе журнала (без зависимостей — тестируется напрямую).

/** Части даты/времени момента в часовом поясе `timeZone` (IANA); без него — пояс устройства. */
function zonedParts(isoDateTime: string, timeZone?: string) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date(isoDateTime));
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "00";
  return { day: get("day"), month: get("month"), year: get("year"), hour: get("hour"), minute: get("minute") };
}

/** "03.09.2026, 14:05" — время в поясе журнала (профиль), как и заголовки дней; без пояса — устройства. */
export function formatSessionDateTime(isoDateTime: string, timeZone?: string): string {
  const p = zonedParts(isoDateTime, timeZone);
  return `${p.day}.${p.month}.${p.year}, ${p.hour}:${p.minute}`;
}

/** "14:05" в поясе журнала (дату несёт заголовок дня в ленте — тот же пояс, localDateKey). */
export function formatSessionTime(isoDateTime: string, timeZone?: string): string {
  const p = zonedParts(isoDateTime, timeZone);
  return `${p.hour}:${p.minute}`;
}

/** "03.09.2026" — дата момента в поясе журнала (профиль), не устройства: запись после полуночи по поясу профиля
 * не должна уезжать на соседний день. */
export function formatSessionDate(isoDateTime: string, timeZone?: string): string {
  const p = zonedParts(isoDateTime, timeZone);
  return `${p.day}.${p.month}.${p.year}`;
}
