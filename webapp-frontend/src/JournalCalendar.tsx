import { buildMonthGrid, monthLabel, WEEKDAY_HEADERS } from "./journalCalendarModel";

/** Месяц-бар «‹ Октябрь 2026 ›» и раскрывающийся календарь (#256): Пн-первая
 * сетка, точка у дня с хотя бы одной завершённой тренировкой, тап по дню
 * выбирает его (повторный — снимает). Данные и часовой пояс приходят снаружи. */
export function JournalCalendar({
  month, dayCounts, selectedDay, today, expanded, onToggleExpanded, onShift, onToggleDay,
}: {
  month: string;
  dayCounts: Map<string, number>;
  selectedDay: string | null;
  today: string;
  expanded: boolean;
  onToggleExpanded: () => void;
  onShift: (delta: number) => void;
  onToggleDay: (date: string) => void;
}) {
  return (
    <div className="journal-calendar">
      <div className="journal-month-bar">
        <button type="button" className="journal-month-arrow" aria-label="Предыдущий месяц" onClick={() => onShift(-1)}>
          ‹
        </button>
        <button
          type="button"
          className="journal-month-label"
          aria-expanded={expanded}
          onClick={onToggleExpanded}
        >
          {monthLabel(month)} {expanded ? "▴" : "▾"}
        </button>
        <button type="button" className="journal-month-arrow" aria-label="Следующий месяц" onClick={() => onShift(1)}>
          ›
        </button>
      </div>
      {expanded && (
        <div className="journal-calendar-grid" role="grid" aria-label={monthLabel(month)}>
          <div className="journal-calendar-row" role="row">
            {WEEKDAY_HEADERS.map((name) => (
              <span key={name} className="journal-calendar-weekday" role="columnheader">{name}</span>
            ))}
          </div>
          {buildMonthGrid(month).map((week, weekIndex) => (
            <div className="journal-calendar-row" role="row" key={weekIndex}>
              {week.map((date, cellIndex) => {
                if (date === null) {
                  return <span key={cellIndex} className="journal-calendar-cell journal-calendar-empty" role="gridcell" />;
                }
                const count = dayCounts.get(date) ?? 0;
                const classes = ["journal-calendar-cell", "journal-calendar-day"];
                if (date === selectedDay) classes.push("journal-calendar-selected");
                if (date === today) classes.push("journal-calendar-today");
                return (
                  <button
                    key={date}
                    type="button"
                    role="gridcell"
                    className={classes.join(" ")}
                    data-date={date}
                    data-has-training={count > 0 ? "true" : "false"}
                    aria-pressed={date === selectedDay}
                    aria-label={`${Number(date.slice(8))}${count > 0 ? `, тренировок: ${count}` : ""}`}
                    onClick={() => onToggleDay(date)}
                  >
                    <span>{Number(date.slice(8))}</span>
                    {count > 0 && <span className="journal-calendar-dot" aria-hidden="true" />}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
