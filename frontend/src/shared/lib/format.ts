export const currency = (value: string | null | undefined, unit = "EUR") =>
  value == null
    ? "Unresolved"
    : new Intl.NumberFormat("en-FI", {
        style: "currency",
        currency: unit,
      }).format(Number(value));
export const dateTime = (value: string) =>
  new Intl.DateTimeFormat("en-FI", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Helsinki",
  }).format(new Date(value));
export const title = (status: string) =>
  status.replaceAll("_", " ").replace(/^./, (s) => s.toUpperCase());
