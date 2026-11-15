import { expect, test, type Page } from "@playwright/test";
import type { Conversation } from "../src/shared/api/types";
import { proposal } from "./support/proposalFixture";
import { ids, json, mockSignedIn, session } from "./support/schedulerFixtures";

// A disrupted standing-order run starts a conversation whose first message has role "system".
// The message is written by the server, not typed by the customer. Mocked API.

const at = "2026-11-14T08:00:00Z";
const systemText =
  "Your standing order Breakfast dairy could not run on 13 Nov 2026.\n\n" +
  "- Whole milk 10 L: price moved from 13.68 to 16.40 EUR\n" +
  "- Cream 1 L: available at the agreed price";
const disrupted: Conversation = {
  id: ids.conversation,
  title: "Standing order 13 Nov 2026: needs your attention",
  created_at: at,
  updated_at: at,
  busy: false,
  cart_editable: false,
  purchases: [proposal],
  messages: [
    { id: 1, role: "system", text: systemText, created_at: at },
    {
      id: 2,
      role: "assistant",
      text: "I rebuilt the basket at today's prices. Review it and confirm to restart.",
      created_at: at,
      proposal_id: ids.proposal,
    },
  ],
};

async function open(page: Page, conversation: Conversation = disrupted) {
  await mockSignedIn(page);
  await page.route(`**/api/conversations/${ids.conversation}`, (route) =>
    json(route, conversation),
  );
  await page.route(`**/api/conversations/${ids.conversation}/events`, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: ": heartbeat\n\n",
    }),
  );
  await page.route(`**/api/purchases/${ids.proposal}`, (route) =>
    json(route, proposal),
  );
  await page.goto(`/conversations/${ids.conversation}`);
}
const systemMessage = (page: Page) =>
  page.getByRole("article", { name: "System message" });

test("a system first message renders as a neutral banner, not a chat bubble", async ({
  page,
}) => {
  await open(page);
  const banner = systemMessage(page);
  await expect(banner).toHaveCount(1);
  await expect(banner).toContainText("Valio Aimo system");
  await expect(banner).toContainText("Your standing order Breakfast dairy");
  await expect(banner).toContainText("price moved from 13.68 to 16.40 EUR");
  // Text is shown as given, with its line breaks.
  const body = banner.getByText("Cream 1 L: available at the agreed price");
  expect(await body.evaluate((e) => getComputedStyle(e).whiteSpace)).toBe(
    "pre-wrap",
  );
  // Not styled or labelled as the customer or the assistant.
  await expect(banner).not.toContainText("You •");
  await expect(banner).not.toContainText("Aimo •");
  await expect(banner.getByRole("button")).toHaveCount(0);
  await expect(banner.getByRole("textbox")).toHaveCount(0);
  // The other two roles keep their own look.
  await expect(
    page.getByRole("article", { name: "System message" }),
  ).toHaveCount(1);
  await expect(page.getByText("I rebuilt the basket")).toBeVisible();
  await expect(page.getByText("Aimo •")).toHaveCount(1);
});

test("the conversation still shows the composer and the purchase cards", async ({
  page,
}) => {
  await open(page);
  await expect(
    page.getByRole("list", { name: "Proposed items" }),
  ).toContainText("Spaghetti 5 kg");
  await expect(page.getByLabel("Continue the conversation")).toBeEnabled();
  await expect(page.getByText(disrupted.title).first()).toBeVisible();
});

test("the customer can reply and the reply is a user message", async ({
  page,
}) => {
  await open(page);
  let sent: { text?: string; idempotency_key?: string } = {};
  await page.route(
    `**/api/conversations/${ids.conversation}/messages`,
    (route) => {
      sent = route.request().postDataJSON();
      expect(route.request().headers()["x-csrf-token"]).toBe(
        session.csrf_token,
      );
      return json(route, {
        ...disrupted,
        messages: [
          ...disrupted.messages,
          { id: 3, role: "user", text: sent.text, created_at: at },
        ],
      });
    },
  );
  await page
    .getByLabel("Continue the conversation")
    .fill("Use the substitute.");
  await page.getByRole("button", { name: "Send Order Request" }).click();
  await expect(page.getByText("You •")).toHaveCount(1);
  await expect(page.getByText("Use the substitute.")).toBeVisible();
  expect(sent.text).toBe("Use the substitute.");
  await expect(systemMessage(page)).toHaveCount(1);
});

test("a system message is never mistaken for the customer's retry text", async ({
  page,
}) => {
  const retry = { text: "Please keep my cream order", idempotency_key: "k-1" };
  await open(page, { ...disrupted, retry_message: retry });
  await expect(page.getByLabel("Continue the conversation")).toHaveValue(
    retry.text,
  );
  await expect(systemMessage(page)).not.toContainText(retry.text);
  await expect(systemMessage(page).getByRole("button")).toHaveCount(0);
});

for (const width of [1440, 390]) {
  test(`the system banner fits ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page);
    await expect(systemMessage(page)).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    const box = await systemMessage(page).boundingBox();
    expect(box && box.x >= 0 && box.x + box.width <= width).toBeTruthy();
  });
}
