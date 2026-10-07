// Quintacle's day boundary is Eastern Time, whatever the device or browser
// thinks — `toISOString()` is UTC, which rolled "today" over to tomorrow
// every evening after ~8pm ET (right when the nightly journal gets written).
export const TIME_ZONE = "America/New_York";

const isoFormat = new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit" });

// YYYY-MM-DD for the current Eastern date.
export function todayIso(): string {
  return isoFormat.format(new Date());
}

// YYYY-MM-DD for today in Eastern, shifted by whole years (Feb 29 rolls to Mar 1).
export function yearsAgoIso(years: number): string {
  const [y, m, d] = todayIso().split("-").map(Number);
  return new Date(Date.UTC(y - years, m - 1, d)).toISOString().slice(0, 10);
}

// YYYY-MM-DD from a calendar Date built with `new Date(y, m, d)` — reads its
// local fields, since those are what the calendar constructed it from.
export function calendarIso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// First of the current Eastern month, as a local calendar Date.
export function currentMonthStart(): Date {
  const [y, m] = todayIso().split("-").map(Number);
  return new Date(y, m - 1, 1);
}
