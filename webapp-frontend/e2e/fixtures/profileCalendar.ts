/** Profile currently counts UTC calendar dates. PATCH /sessions accepts a user-local
 * date and preserves the existing local time, so those are different contracts.
 * Prepare only the two existing synthetic D2 facts immediately before reading Profile;
 * a once-per-job seed can otherwise age across midnight during the full suite. */
export function performedOnForUtcAge(performedAt: string, now: Date, daysAgo: number, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(
    new Date(Date.parse(performedAt) + (
      Date.parse(`${now.toISOString().slice(0, 10)}T00:00:00Z`)
      - Date.parse(`${new Date(performedAt).toISOString().slice(0, 10)}T00:00:00Z`)
      - daysAgo * 86_400_000
    )),
  );
}
