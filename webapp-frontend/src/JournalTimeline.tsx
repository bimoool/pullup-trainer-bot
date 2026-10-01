import type { ReactNode } from "react";

import { dayLabel, groupByWeekAndDay, weekLabel } from "./journalCalendar";

/** Лента Журнала (#256): полоса недели (Пн–Вс) → заголовок дня → карточки.
 * Карточки (v2 и legacy) приходят готовыми — таймлайн ничего о них не знает. */
export function JournalTimeline({ entries }: { entries: { date: string; node: ReactNode }[] }) {
  const weeks = groupByWeekAndDay(entries.map(({ date, node }) => ({ date, item: node })));
  return (
    <div>
      {weeks.map((week) => (
        <section key={week.weekStart} className="journal-week" data-week-start={week.weekStart}>
          <p className="journal-week-header">{weekLabel(week.weekStart)}</p>
          {week.days.map((day) => (
            <div key={day.date} className="journal-day" data-date={day.date}>
              <p className="journal-day-header">{dayLabel(day.date)}</p>
              <div className="history-list">{day.items}</div>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
