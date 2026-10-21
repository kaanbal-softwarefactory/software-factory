export function calendarDay(date: Date, timezone: string) {
  const parts = new Intl.DateTimeFormat("en", { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(date);
  const value = (type: string) => parts.find((part) => part.type === type)?.value;
  return `${value("year")}-${value("month")}-${value("day")}`;
}
export function shiftDay(day: string, offset: number) {
  return new Date(Date.parse(`${day}T12:00:00Z`) + offset * 86400000).toISOString().slice(0, 10);
}
export function monday(day: string) {
  const weekday = new Date(`${day}T12:00:00Z`).getUTCDay();
  return shiftDay(day, -((weekday + 6) % 7));
}
export function calendarWindow(start: string) {
  // Cover every IANA offset and DST boundary; the view groups by the actual business day.
  return { from: `${shiftDay(start, -1)}T00:00:00Z`, to: `${shiftDay(start, 8)}T00:00:00Z` };
}
