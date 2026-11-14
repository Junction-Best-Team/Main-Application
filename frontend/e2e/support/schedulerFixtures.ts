import type { Page, Route } from "@playwright/test";
import type {
  OrderListItem,
  OrdersResponse,
  Schedule,
  ScheduleDetail,
  ScheduleLine,
  ScheduleRun,
  ScheduleTerms,
  Session,
} from "../../src/shared/api/types";

// Typed fixtures for the standing-order screens. Every value is made up (mock data); the
// shapes come from the generated schema, so a field that changes breaks the build here first.
export const session: Session = {
  username: "buyer",
  buyer_id: "demo-hotel",
  csrf_token: "test-csrf",
  role: "approver",
  scheduler_demo_mode: false,
};
export const demoSession: Session = { ...session, scheduler_demo_mode: true };
export const ids = {
  schedule: "5e1c6c33-4a0b-4c0e-9d2b-0f1f6c0a7a01",
  pausedSchedule: "5e1c6c33-4a0b-4c0e-9d2b-0f1f6c0a7a02",
  stoppedSchedule: "5e1c6c33-4a0b-4c0e-9d2b-0f1f6c0a7a03",
  successor: "5e1c6c33-4a0b-4c0e-9d2b-0f1f6c0a7a04",
  sourceOrder: "7d2f9a10-6c3b-4e8f-a1b2-c3d4e5f60718",
  conversation: "fa0d5e73-f5a5-4594-a1c5-e4c1a24eebae",
  proposal: "b7b7dc8d-8e75-4f79-ac23-649ed1e5fd96",
  order: "c1a2b3c4-d5e6-4f70-8a9b-0c1d2e3f4a5b",
};
const timestamp = "2026-11-14T10:00:00+02:00";

export const milk: ScheduleLine = {
  product_id: "464306",
  name: "Whole milk 10 L",
  amount: "8",
  unit: "L",
  sales_quantity: "8",
  sales_unit: "BIB",
  unit_net: "12.00",
  unit_gross: "13.68",
  tax_rate: "14",
  line_gross: "109.44",
  accepted_substitutes: [
    {
      product_id: "464398",
      name: "Organic whole milk 10 L",
      unit_gross: "14.10",
      sales_unit: "BIB",
    },
  ],
  price_range_pct: "7.50",
};
export const cream: ScheduleLine = {
  product_id: "464400",
  name: "Cream 1 L",
  amount: "4",
  unit: "L",
  sales_quantity: "4",
  sales_unit: "KTN",
  unit_net: "5.00",
  unit_gross: "5.70",
  tax_rate: "14",
  line_gross: "22.80",
  accepted_substitutes: [],
  price_range_pct: "0.00",
};

export const schedule: Schedule = {
  id: ids.schedule,
  title: "Breakfast dairy",
  status: "active",
  stop_reason: null,
  source_order_id: ids.sourceOrder,
  supersedes_id: null,
  replaced_by: null,
  recurrence: { kind: "weekdays", weekdays: [4], every_weeks: 1 },
  first_run_date: "2026-11-20",
  valid_until: "2027-11-20",
  next_run_date: "2026-11-20",
  paused_at: null,
  delivery_offset_days: 2,
  currency: "EUR",
  agreed_gross_total: "132.24",
  price_ceiling_gross: "150.00",
  lines: [milk, cream],
  last_run: null,
  conversation_id: null,
  created_at: timestamp,
  updated_at: timestamp,
};
export const pausedSchedule: Schedule = {
  ...schedule,
  id: ids.pausedSchedule,
  title: "Weekend cheeses",
  status: "paused",
  paused_at: timestamp,
  recurrence: { kind: "days", interval: 4, every_weeks: 1 },
};
export const disruptedRun: ScheduleRun = {
  id: "run-3",
  scheduled_date: "2026-11-13",
  delivery_date: "2026-11-15",
  status: "disrupted",
  reason_code: "PRICE_OUTSIDE_RANGE",
  reason: {
    codes: ["PRICE_OUTSIDE_RANGE"],
    lines: [
      {
        product_id: "464306",
        name: "Whole milk 10 L",
        status: "price_outside_range",
        agreed_gross: "13.68",
        current_gross: "16.40",
        available_quantity: null,
        substitute_product_id: null,
        note: null,
      },
      {
        product_id: "464400",
        name: "Cream 1 L",
        status: "available_same_price",
      },
    ],
    agreed_gross_total: "132.24",
    current_gross_total: "154.00",
  },
  substitutions: [],
  proposal_id: ids.proposal,
  order_id: null,
  conversation_id: ids.conversation,
  updated_at: timestamp,
};
export const stoppedSchedule: Schedule = {
  ...schedule,
  id: ids.stoppedSchedule,
  title: "Seasonal vegetables",
  status: "stopped",
  stop_reason: "PRICE_OUTSIDE_RANGE",
  next_run_date: null,
  last_run: disruptedRun,
  conversation_id: ids.conversation,
};
export const committedRun: ScheduleRun = {
  id: "run-1",
  scheduled_date: "2026-11-06",
  delivery_date: "2026-11-08",
  status: "committed",
  reason_code: null,
  reason: null,
  substitutions: [],
  proposal_id: ids.proposal,
  order_id: ids.order,
  conversation_id: null,
  updated_at: timestamp,
};
export const skippedRun: ScheduleRun = {
  id: "run-2",
  scheduled_date: "2026-11-09",
  delivery_date: "2026-11-11",
  status: "skipped",
  reason_code: "PAUSED",
  reason: null,
  substitutions: [],
  proposal_id: null,
  order_id: null,
  conversation_id: null,
  updated_at: timestamp,
};
export const detail = (
  s: Schedule,
  runs: ScheduleRun[] = [],
): ScheduleDetail => ({
  ...s,
  runs,
  runs_next_offset: null,
});

export const terms: ScheduleTerms = {
  source_order_id: ids.sourceOrder,
  title: "Breakfast dairy",
  lines: [milk, cream],
  currency: "EUR",
  gross_total: "132.24",
  policy_outcome: "ready_to_commit",
  terms_fingerprint: "f".repeat(64),
  delivery_offset_days: 2,
  recurrence: { kind: "weekdays", weekdays: [4], every_weeks: 1 },
  first_run_date: "2026-11-20",
  valid_until: "2027-11-20",
  next_dates: ["2026-11-20", "2026-11-27", "2026-12-04"],
  blocking_reasons: [],
};

const order = (
  o: Partial<OrderListItem> & Pick<OrderListItem, "status">,
): OrderListItem => ({
  title: "Hotel breakfast",
  paused: false,
  line_count: 2,
  gross_total: "132.24",
  currency: "EUR",
  updated_at: timestamp,
  ...o,
});
export const orders: OrderListItem[] = [
  order({
    status: "scheduled",
    title: "Breakfast dairy",
    scheduled_for: "2026-11-20",
    schedule_id: ids.schedule,
    schedule_title: "Breakfast dairy",
  }),
  order({
    status: "scheduled",
    title: "Weekend cheeses",
    scheduled_for: "2026-11-24",
    paused: true,
    schedule_id: ids.pausedSchedule,
    schedule_title: "Weekend cheeses",
  }),
  order({
    status: "pending",
    title: "Carbonara for 200",
    proposal_id: ids.proposal,
  }),
  order({
    status: "placed",
    title: "Hotel breakfast",
    proposal_id: ids.proposal,
    order_id: ids.sourceOrder,
  }),
  order({
    status: "cancelled",
    title: "Old basket",
    proposal_id: "11111111-1111-4111-8111-111111111111",
    cancel_reason: "customer_cancelled",
  }),
];
export const ordersPage = (
  items = orders,
  next: number | null = null,
  total = items.length,
): OrdersResponse => ({
  items,
  next_offset: next,
  total,
});

export const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
export const problem = (
  route: Route,
  status: number,
  code: string,
  message: string,
  details?: unknown,
) =>
  json(
    route,
    { error: { code, message, ...(details === undefined ? {} : { details }) } },
    status,
  );

// Signs in and answers the calls every page makes. Register page-specific routes AFTER this.
export async function mockSignedIn(page: Page, demoMode = false) {
  await page.route("**/api/session", (route) =>
    json(route, demoMode ? demoSession : session),
  );
  await page.route("**/api/conversations?*", (route) =>
    json(route, { items: [], next_offset: null }),
  );
  await page.route("**/api/logout", (route) => route.fulfill({ status: 204 }));
}
