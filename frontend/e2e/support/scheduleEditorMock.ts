import type { Page, Route } from "@playwright/test";
import { addDays, FRIDAY } from "./dates";
import {
  json,
  mockSignedIn,
  problem,
  ids,
  schedule,
  detail,
} from "./schedulerFixtures";
import type { Schedule, ScheduleTerms } from "../../src/shared/api/types";

// A tiny router for the create/edit specs. Handlers are keyed "METHOD /path" (the path has no
// query string). Every request is recorded in `calls`; an unmocked call answers 404 and is
// recorded in `unmocked` so a spec can assert nothing unexpected was requested.
export type Call = { key: string; body: Record<string, unknown> | null };
export type Handler = (
  route: Route,
  body: Record<string, unknown> | null,
  nth: number,
) => Promise<void> | void;

export async function mockApi(page: Page, handlers: Record<string, Handler>) {
  await mockSignedIn(page);
  const calls: Call[] = [];
  const unmocked: string[] = [];
  const counts = new Map<string, number>();
  await page.route(
    (url) => /^\/api\/(schedules|orders)/.test(url.pathname),
    async (route) => {
      const request = route.request();
      const key = `${request.method()} ${new URL(request.url()).pathname}`;
      const raw = request.postData();
      const body = raw ? (JSON.parse(raw) as Record<string, unknown>) : null;
      calls.push({ key, body });
      const nth = counts.get(key) ?? 0;
      counts.set(key, nth + 1);
      const handler = handlers[key];
      if (!handler) {
        unmocked.push(key);
        return problem(route, 404, "UNMOCKED", `No mock for ${key}`);
      }
      return handler(route, body, nth);
    },
  );
  const bodies = (key: string) =>
    calls.filter((c) => c.key === key).map((c) => c.body);
  return { calls, unmocked, bodies };
}

export const created = (over: Partial<Schedule> = {}): Schedule => ({
  ...schedule,
  id: ids.successor,
  ...over,
});

// The page that opens after create/replace: any detail answers, the specs only assert the URL.
export const detailHandler: Handler = (route) => json(route, detail(created()));

export const termsWith = (
  over: Partial<ScheduleTerms> = {},
): ScheduleTerms => ({
  source_order_id: ids.sourceOrder,
  title: "Breakfast dairy",
  lines: [],
  currency: "EUR",
  gross_total: "132.24",
  policy_outcome: "ready_to_commit",
  terms_fingerprint: "f".repeat(64),
  delivery_offset_days: 2,
  recurrence: { kind: "weekdays", weekdays: [4], every_weeks: 1 },
  first_run_date: FRIDAY,
  valid_until: addDays(FRIDAY, 365),
  next_dates: [FRIDAY, addDays(FRIDAY, 7), addDays(FRIDAY, 14)],
  blocking_reasons: [],
  ...over,
});

export const delay = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));
