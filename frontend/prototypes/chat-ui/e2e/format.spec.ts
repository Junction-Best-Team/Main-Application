import { expect, test } from "./test";
import { formatDateTime, formatMoney } from "../src/format";

test("formats money with the default locale setting", () => {
  expect(formatMoney("1234.5")).toBe("€1,234.50");
  expect(formatMoney(null)).toBe("Unresolved");
});

test("switching locale is one argument/setting", () => {
  expect(formatMoney("1234.5", "EUR", "fi-FI").replace(/\s/g, " ")).toBe("1 234,50 €");
});

test("formats dates in Helsinki time", () => {
  expect(formatDateTime("2026-11-14T10:00:00Z", "en-GB")).toContain("12:00");
});
