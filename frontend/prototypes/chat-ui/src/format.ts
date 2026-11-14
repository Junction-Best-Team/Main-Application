// Single locale setting for all price/date formatting. Change this one line
// (e.g. to "fi-FI") to switch the whole app.
export const LOCALE = "en-FI";

export const formatMoney = (
  value: string | null | undefined,
  unit = "EUR",
  locale = LOCALE,
) =>
  value == null
    ? "Unresolved"
    : new Intl.NumberFormat(locale, { style: "currency", currency: unit }).format(Number(value));

export const formatDateTime = (value: string, locale = LOCALE) =>
  new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Helsinki",
  }).format(new Date(value));
