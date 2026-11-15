import { expect, test, type Page } from "@playwright/test";
import { json, mockSignedIn, ids, session } from "./support/schedulerFixtures";
import { proposal } from "./support/proposalFixture";

// Debug-only "Copy" link next to error messages. Mocked at the browser<->API edge; the clipboard
// is stubbed in the page (or granted for the real-clipboard case). No live service is touched.
const SENTENCE = "The service could not complete this request. Try again.";
const conversationId = ids.conversation;
const timestamp = "2026-11-14T12:00:00Z";
const typed = "Secret pancetta order for forty guests";

const blank = {
  id: conversationId,
  title: "Carbonara for 200",
  created_at: timestamp,
  updated_at: timestamp,
  messages: [] as unknown[],
  purchases: [] as unknown[],
  busy: false,
  retry_message: null,
};

const copy = (page: Page) =>
  page.getByRole("button", { name: "Copy", exact: true });

async function mockChat(page: Page, conversation: unknown = blank) {
  await mockSignedIn(page);
  await page.route("**/api/purchases?*", (route) =>
    json(route, { items: [], next_offset: null }),
  );
  await page.route(`**/api/conversations/${conversationId}/events`, (route) =>
    route.fulfill({ contentType: "text/event-stream", body: ": keep\n\n" }),
  );
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    json(route, conversation),
  );
}

// Every send answers 500 with the server's SERVER_ERROR text and a request id header.
async function failSends(page: Page, status = 500) {
  await page.route(`**/api/conversations/${conversationId}/messages`, (route) =>
    route.fulfill({
      status,
      headers: { "x-request-id": "req-abc123" },
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "SERVER_ERROR", message: SENTENCE },
      }),
    }),
  );
}

// Captures writeText calls; `mode` picks how the clipboard behaves.
async function stubClipboard(
  page: Page,
  mode: "ok" | "reject" | "missing" = "ok",
) {
  await page.addInitScript((m) => {
    const w = window as unknown as { __copied: string[] };
    w.__copied = [];
    if (m === "missing") {
      Object.defineProperty(navigator, "clipboard", { value: undefined });
      document.execCommand = (command: string) => {
        const area = document.activeElement as HTMLTextAreaElement | null;
        if (command === "copy" && area?.value) w.__copied.push(area.value);
        return true;
      };
      return;
    }
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: (text: string) => {
          if (m === "reject") return Promise.reject(new Error("denied"));
          w.__copied.push(text);
          return Promise.resolve();
        },
      },
    });
    if (m === "reject") document.execCommand = () => false;
  }, mode);
}
const copied = (page: Page) =>
  page.evaluate(() => (window as unknown as { __copied: string[] }).__copied);

async function sendTyped(page: Page, url = `/conversations/${conversationId}`) {
  await page.goto(url);
  await page.getByLabel("Continue the conversation").fill(typed);
  await page.getByRole("button", { name: "Send Order Request" }).click();
}

test("normal mode shows the error but no Copy link", async ({ page }) => {
  await mockChat(page);
  await failSends(page);
  await sendTyped(page);
  await expect(page.getByRole("alert").first()).toContainText(SENTENCE);
  await expect(copy(page)).toHaveCount(0);
});

test("debug mode copies a debug message with the request context and no private data", async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem("aimo.debug", "1"));
  await stubClipboard(page);
  await page.clock.install();
  await mockChat(page);
  await failSends(page);
  await sendTyped(page, `/conversations/${conversationId}?utm=private-query`);
  await expect(page.getByRole("alert").first()).toContainText(SENTENCE);
  const link = copy(page);
  await expect(link).toBeVisible();
  await link.click();
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();
  const [text] = await copied(page);
  expect(text).toContain("req-abc123");
  expect(text).toMatch(/status: 500/);
  expect(text).toContain("SERVER_ERROR");
  expect(text).toContain(SENTENCE);
  expect(text).toMatch(/method: POST/);
  expect(text).toContain(`/api/conversations/${conversationId}/messages`);
  expect(text).toContain(`/conversations/${conversationId}`);
  expect(text).toMatch(/timestamp: \d{4}-\d{2}-\d{2}T/);
  expect(text).toMatch(/user-agent: .+/i);
  expect(text).not.toContain("utm=");
  expect(text).not.toContain("private-query");
  expect(text).not.toContain("?");
  expect(text).not.toContain(session.csrf_token);
  expect(text).not.toMatch(/cookie/i);
  expect(text).not.toContain(typed);
  expect(text).not.toContain("idempotency");
  // "Copied" shows for two seconds, then the link returns.
  await page.clock.fastForward(1900);
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();
  await page.clock.fastForward(300);
  await expect(copy(page)).toBeVisible();
  await expect(page.getByRole("button", { name: "Copied" })).toHaveCount(0);
});

test("the real clipboard receives the debug message", async ({
  page,
  context,
  browserName,
}) => {
  test.skip(browserName !== "chromium", "clipboard permissions are Chromium");
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.addInitScript(() => localStorage.setItem("aimo.debug", "1"));
  await mockChat(page);
  await failSends(page);
  await sendTyped(page);
  await copy(page).click();
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();
  const text = await page.evaluate(() => navigator.clipboard.readText());
  expect(text).toContain("req-abc123");
  expect(text).toContain("status: 500");
});

test("falls back to a hidden textarea when the clipboard API is missing", async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem("aimo.debug", "1"));
  await stubClipboard(page, "missing");
  await mockChat(page);
  await failSends(page);
  await sendTyped(page);
  await copy(page).click();
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();
  const [text] = await copied(page);
  expect(text).toContain("req-abc123");
  await expect(page.locator("textarea[readonly][aria-hidden]")).toHaveCount(0);
});

test("?debug=1 turns debug mode on and persists; ?debug=0 turns it off", async ({
  page,
}) => {
  await mockChat(page);
  await failSends(page);
  await sendTyped(page, `/conversations/${conversationId}?debug=1`);
  await expect(copy(page)).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("aimo.debug"))).toBe(
    "1",
  );
  // A later visit without the parameter stays in debug mode.
  await sendTyped(page);
  await expect(copy(page)).toBeVisible();
  // ?debug=0 clears it.
  await sendTyped(page, `/conversations/${conversationId}?debug=0`);
  await expect(page.getByRole("alert").first()).toContainText(SENTENCE);
  await expect(copy(page)).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("aimo.debug"))).toBe(
    null,
  );
  await sendTyped(page);
  await expect(page.getByRole("alert").first()).toContainText(SENTENCE);
  await expect(copy(page)).toHaveCount(0);
});

test("a failing clipboard never breaks the page", async ({ page }) => {
  const pageErrors: Error[] = [];
  page.on("pageerror", (e) => pageErrors.push(e));
  await page.addInitScript(() => localStorage.setItem("aimo.debug", "1"));
  await stubClipboard(page, "reject");
  await mockChat(page);
  await failSends(page);
  await sendTyped(page);
  await copy(page).click();
  await page.waitForTimeout(300);
  await expect(page.getByRole("alert").first()).toContainText(SENTENCE);
  await expect(copy(page)).toBeVisible();
  await expect(page.getByRole("button", { name: "Copied" })).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test("debug mode also covers a failed retry and a failed conversation load", async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem("aimo.debug", "1"));
  await stubClipboard(page);
  await mockChat(page);
  await failSends(page);
  await sendTyped(page);
  await expect(copy(page)).toBeVisible();
  // The draft stays; Retry request fails again and the link is still there.
  await page.getByRole("button", { name: "Retry request" }).click();
  await expect(page.getByRole("alert").first()).toContainText(SENTENCE);
  await copy(page).click();
  expect((await copied(page))[0]).toContain("method: POST");

  // A conversation that cannot be loaded.
  await page.unroute(`**/api/conversations/${conversationId}`);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({
      status: 500,
      headers: { "x-request-id": "req-load-1" },
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "SERVER_ERROR", message: SENTENCE },
      }),
    }),
  );
  await page.goto(`/conversations/${conversationId}`);
  await expect(page.getByRole("alert").first()).toContainText(SENTENCE);
  await copy(page).first().click();
  const text = (await copied(page))[0];
  expect(text).toContain("req-load-1");
  expect(text).toContain("method: GET");
});

test("debug mode covers a failed Overview confirm", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("aimo.debug", "1"));
  await stubClipboard(page);
  const ready = {
    ...proposal,
    policy_outcome: "ready_to_commit",
    approval_status: "not_required",
    approval_id: null,
    approval_url: null,
    can_decide: false,
    next_action: { type: "commit" },
  };
  await mockChat(page, {
    ...blank,
    messages: [
      {
        id: 1,
        role: "assistant",
        text: "Review the verified basket before confirming.",
        created_at: timestamp,
        proposal_id: ids.proposal,
        meal_plan: {
          title: "Carbonara",
          portions: 200,
          ingredients: [{ name: "Spaghetti", amount: "20", unit: "KG" }],
          notes: [],
        },
      },
    ],
    purchases: [ready],
  });
  await page.route(`**/api/purchases/${ids.proposal}`, (route) =>
    json(route, ready),
  );
  await page.route(`**/api/purchases/${ids.proposal}/confirm`, (route) =>
    route.fulfill({
      status: 409,
      headers: { "x-request-id": "req-confirm-9" },
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "DECISION_CLOSED", message: "This purchase is closed." },
      }),
    }),
  );
  await page.goto(`/conversations/${conversationId}`);
  const panel = page.getByRole("complementary", { name: "Overview" });
  await panel.getByRole("button", { name: "Confirm purchase" }).click();
  await expect(panel.getByRole("alert")).toContainText(
    "This purchase is closed.",
  );
  await panel.getByRole("button", { name: "Copy", exact: true }).click();
  const text = (await copied(page))[0];
  expect(text).toContain("req-confirm-9");
  expect(text).toContain("DECISION_CLOSED");
  expect(text).toContain("status: 409");
  expect(text).toContain(`/api/purchases/${ids.proposal}/confirm`);
});

const MARKER = "UPSTREAM-HTML-MARKER-7731";

async function debugSetup(page: Page) {
  await page.addInitScript(() => localStorage.setItem("aimo.debug", "1"));
  await stubClipboard(page);
  await mockChat(page);
}

test("a non-JSON 502 from the ingress copies kind, content type and no body text", async ({
  page,
}) => {
  await debugSetup(page);
  await page.route(`**/api/conversations/${conversationId}/messages`, (route) =>
    route.fulfill({
      status: 502,
      contentType: "text/html",
      body: `<html><body><h1>Upstream page ${MARKER}</h1></body></html>`,
    }),
  );
  await sendTyped(page);
  await expect(page.getByRole("alert").first()).toContainText(SENTENCE);
  await copy(page).click();
  const text = (await copied(page))[0];
  expect(text).toContain("body: not JSON");
  expect(text).toMatch(/content-type: text\/html/);
  expect(text).toContain("status: 502");
  expect(text).toContain("x-request-id: none");
  expect(text).toMatch(/elapsed-ms: \d+/);
  expect(text).toMatch(/status-text: .+/);
  expect(text).not.toContain(MARKER);
  expect(text).not.toContain("Upstream page");
});

test("a JSON error envelope is reported as such with its elapsed time", async ({
  page,
}) => {
  await debugSetup(page);
  await failSends(page);
  await sendTyped(page);
  await copy(page).click();
  const text = (await copied(page))[0];
  expect(text).toContain("body: JSON envelope");
  expect(text).toContain("content-type: application/json");
  expect(text).toMatch(/elapsed-ms: \d+/);
});

test("a network failure copies status 0 with no response headers", async ({
  page,
}) => {
  await debugSetup(page);
  await page.route(`**/api/conversations/${conversationId}/messages`, (route) =>
    route.abort("connectionreset"),
  );
  await sendTyped(page);
  await expect(page.getByRole("alert").first()).toContainText(
    "Could not reach the service.",
  );
  await copy(page).click();
  const text = (await copied(page))[0];
  expect(text).toContain("status: 0");
  expect(text).toContain("error-code: NETWORK_ERROR");
  expect(text).toMatch(/elapsed-ms: \d+/);
  expect(text).toContain("response: none (network failure)");
  expect(text).not.toContain("x-request-id");
  expect(text).not.toContain("content-type");
});
