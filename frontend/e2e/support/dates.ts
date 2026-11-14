// The first run date must be tomorrow or later and at most 365 days ahead, so the specs derive
// their dates from today (Helsinki) instead of using fixed calendar dates.
const helsinkiToday = () =>
  new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Helsinki" }).format(
    new Date(),
  );

export const addDays = (isoDate: string, days: number) =>
  new Date(Date.parse(`${isoDate}T00:00:00Z`) + days * 86_400_000)
    .toISOString()
    .slice(0, 10);

// 0 = Monday ... 6 = Sunday, like the API.
const weekday = (isoDate: string) =>
  (new Date(`${isoDate}T00:00:00Z`).getUTCDay() + 6) % 7;

/** The first date at least `minDays` ahead that falls on `day`. */
export function nextWeekday(day: number, minDays = 3) {
  let date = addDays(helsinkiToday(), minDays);
  while (weekday(date) !== day) date = addDays(date, 1);
  return date;
}

export const FRIDAY = nextWeekday(4);
export const MONDAY = nextWeekday(0);

/** A date as the UI prints it (en-FI, medium). */
export const printed = (isoDate: string) =>
  new Intl.DateTimeFormat("en-FI", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(`${isoDate}T00:00:00Z`));
