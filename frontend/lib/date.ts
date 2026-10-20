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

// YYYY-MM-DD shifted by whole days — pure UTC field arithmetic on the given
// calendar date, so no local-zone `new Date()` drift can touch it.
export function addDaysIso(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}

// Monday (YYYY-MM-DD) of the week containing the given YYYY-MM-DD — the
// backend's habit weeks are Monday-anchored (quotas.period_window), and this
// mirrors that grid client-side for layout only. ET-safe: operates on the
// date string's own fields in UTC, never on the browser's local clock.
export function mondayOfWeek(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  const sinceMonday = (dt.getUTCDay() + 6) % 7; // Monday = 0
  return addDaysIso(iso, -sinceMonday);
}
