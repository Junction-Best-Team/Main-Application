import { expect, test, type Page, type Route } from "@playwright/test";
import type { MemoryItem, MemoryMutation } from "../src/shared/api/types";

// Memory settings against authored responses shaped like
// the generated MemoryList / MemoryMutationResponse contract. These prove UI
// behavior only; agent retrieval and the real database are not exercised here.

const session = {
  username: "buyer",
  buyer_id: "demo-hotel",
  csrf_token: "test-csrf",
};
const t0 = "2026-11-14T10:00:00Z";
const conversationId = "fa0d5e73-f5a5-4594-a1c5-e4c1a24eebae";

function item(overrides: Partial<MemoryItem>): MemoryItem {
  return {
    id: crypto.randomUUID(),
    scope: "buyer",
    owner_id: null,
    kind: "default",
    key: "default.portions",
    value: { portions: 200 },
    description: null,
    revision: 1,
    created_at: t0,
    updated_at: t0,
    created_by: "identity-1",
    updated_by: "identity-1",
    source_conversation_id: null,
    source_message_id: null,
    ...overrides,
  };
}

type Write = {
  method: string;
  url: string;
  body: Record<string, unknown>;
  headers: Record<string, string>;
};

/** In-memory stand-in for /api/memories with revisions and error injection. */
async function mockApi(
  page: Page,
  seed: { self?: MemoryItem[]; buyer?: MemoryItem[] } = {},
) {
  const store = { self: seed.self ?? [], buyer: seed.buyer ?? [] };
  const writes: Write[] = [];
  const lists: string[] = [];
  let authenticated = true;
  const fail: { next?: { status: number; code: string; message: string } } = {};
  const listDelay = { ms: 0 };
  const listFailures = { remaining: 0 };

  await page.route("**/api/session", (route) =>
    route.fulfill({
      status: authenticated ? 200 : 401,
      json: authenticated
        ? session
        : { error: { code: "UNAUTHENTICATED", message: "Sign in" } },
    }),
  );
  await page.route("**/api/login", async (route) => {
    authenticated = true;
    await route.fulfill({ json: session });
  });
  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );
  await page.route("**/api/purchases?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );

  const error = (route: Route, status: number, code: string, message: string) =>
    route.fulfill({ status, json: { error: { code, message } } });

  await page.route("**/api/memories**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!authenticated)
      return error(route, 401, "UNAUTHENTICATED", "Sign in to continue.");
    if (request.method() === "GET") {
      lists.push(url.search);
      if (listDelay.ms) await new Promise((r) => setTimeout(r, listDelay.ms));
      if (listFailures.remaining > 0) {
        listFailures.remaining--;
        return error(route, 503, "UNAVAILABLE", "The service is unavailable.");
      }
      const scope =
        url.searchParams.get("scope") === "buyer" ? "buyer" : "self";
      return route.fulfill({
        json: { items: store[scope], next_offset: null },
      });
    }
    const body = request.postDataJSON() as Record<string, unknown>;
    writes.push({
      method: request.method(),
      url: url.pathname,
      body,
      headers: request.headers(),
    });
    if (fail.next) {
      const f = fail.next;
      fail.next = undefined;
      return error(route, f.status, f.code, f.message);
    }
    const now = "2026-11-14T12:30:00Z";
    if (request.method() === "POST" && url.pathname === "/api/memories") {
      const scope = body.scope as "self" | "buyer";
      const created = item({
        scope: scope === "self" ? "user" : "buyer",
        owner_id: scope === "self" ? "identity-1" : null,
        kind: String(body.key).split(".")[0] as MemoryItem["kind"],
        key: String(body.key),
        value: body.value as MemoryItem["value"],
        description: (body.description as string | undefined) ?? null,
        updated_at: now,
      });
      store[scope] = [created, ...store[scope]];
      return route.fulfill({
        json: {
          status: "created",
          memory_id: created.id,
          revision: 1,
          memory: created,
          replayed: false,
        } satisfies MemoryMutation,
      });
    }
    const id = url.pathname.split("/")[3];
    const scope = store.self.some((i) => i.id === id) ? "self" : "buyer";
    const existing = store[scope].find((i) => i.id === id);
    if (!existing)
      return error(route, 404, "MEMORY_NOT_FOUND", "Memory not found.");
    if (body.expected_revision !== existing.revision)
      return error(
        route,
        409,
        "MEMORY_REVISION_CONFLICT",
        `This memory changed; its current revision is ${existing.revision}.`,
      );
    if (url.pathname.endsWith("/delete")) {
      store[scope] = store[scope].filter((i) => i.id !== id);
      return route.fulfill({
        json: {
          status: "deleted",
          memory_id: id,
          revision: existing.revision,
          memory: null,
          replayed: false,
        } satisfies MemoryMutation,
      });
    }
    const updated = {
      ...existing,
      value: body.value as MemoryItem["value"],
      description:
        (body.description as string | undefined) ?? existing.description,
      revision: existing.revision + 1,
      updated_at: now,
    };
    store[scope] = store[scope].map((i) => (i.id === id ? updated : i));
    return route.fulfill({
      json: {
        status: "updated",
        memory_id: id,
        revision: updated.revision,
        memory: updated,
        replayed: false,
      } satisfies MemoryMutation,
    });
  });

  return {
    store,
    writes,
    lists,
    fail,
    listDelay,
    listFailures,
    expireSession: () => {
      authenticated = false;
    },
  };
}

test("direct route shows personal and buyer scopes separately with safe text", async ({
  page,
}) => {
  const hostile = '<img src=x onerror="window.__pwned=1">';
  await mockApi(page, {
    self: [
      item({
        scope: "user",
        owner_id: "identity-1",
        kind: "preference",
        key: "preference.reply_style",
        value: { length: "short", language: "fi" },
      }),
    ],
    buyer: [
      item({ value: { portions: 200 }, description: hostile }),
      item({
        kind: "preference",
        key: "preference.pack_size.cream",
        value: { ingredient: "Cream", amount: "1", unit: "L" },
        source_conversation_id: conversationId,
      }),
      item({
        kind: "instruction",
        key: "instruction.cheaper_first",
        value: { text: "Show cheaper alternatives first." },
      }),
    ],
  });
  await page.goto("/settings/preferences");

  await expect(
    page.getByRole("heading", { level: 1, name: "Memory" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Memories guide suggestions. Purchase rules and confirmation still apply.",
    ),
  ).toBeVisible();
  const mine = page.getByRole("tab", { name: "Personal" });
  await expect(mine).toHaveAttribute("aria-selected", "true");
  const panel = page.getByRole("tabpanel");
  await expect(
    panel.getByRole("heading", { name: "Reply style" }),
  ).toBeVisible();
  await expect(panel.getByText("Short replies · Finnish")).toBeVisible();
  await expect(panel.getByRole("article")).toHaveCount(1);
  await expect(panel.getByText("Usual portions")).toHaveCount(0);

  await page.getByRole("tab", { name: "Shared with buyer" }).click();
  await expect(page).toHaveURL(/scope=buyer/);
  await expect(
    panel.getByText(
      "Used by everyone in demo-hotel. Any buyer approver can manage these memories.",
    ),
  ).toBeVisible();
  await expect(panel.getByText("200 portions")).toBeVisible();
  await expect(panel.getByText("Cream: 1 L")).toBeVisible();
  await expect(panel.getByText(hostile)).toBeVisible();
  await expect(panel.locator("img")).toHaveCount(0);
  expect(await page.evaluate(() => "__pwned" in window)).toBe(false);
  await expect(panel.getByText("Reply style")).toHaveCount(0);
  const packDetails = panel.getByRole("article", {
    name: "Preferred pack size",
  });
  await expect(
    packDetails.getByRole("link", { name: "From a conversation" }),
  ).toBeHidden();
  await packDetails.locator("summary").click();
  await expect(
    packDetails.getByText("Updated", { exact: false }),
  ).toBeVisible();
  await expect(
    panel.getByRole("link", { name: "From a conversation" }),
  ).toHaveAttribute("href", `/conversations/${conversationId}`);
  // Only one item carries a source conversation; internal IDs and keys stay hidden.
  await expect(
    panel.getByRole("link", { name: "From a conversation" }),
  ).toHaveCount(1);
  await expect(panel.getByText("identity-1")).toHaveCount(0);
  await expect(panel.getByText("default.portions")).toHaveCount(0);

  // The scope is preserved on reload of a direct link.
  await page.reload();
  await expect(
    page.getByRole("tab", { name: "Shared with buyer" }),
  ).toHaveAttribute("aria-selected", "true");
});

test("loading, empty and failed-load states with retry", async ({ page }) => {
  const api = await mockApi(page);
  api.listDelay.ms = 600;
  api.listFailures.remaining = 0;
  await page.goto("/settings/preferences");
  await expect(page.getByText("Loading memories…")).toBeVisible();
  await expect(page.getByText("No memories yet")).toBeVisible();
  await page.getByRole("tab", { name: "Shared with buyer" }).click();
  await expect(
    page.getByText("No memories yet", { exact: false }),
  ).toBeVisible();

  api.listDelay.ms = 0;
  // Dev StrictMode repeats the initial fetches, so fail every load until retry.
  api.listFailures.remaining = 100;
  await page.reload();
  const alert = page
    .getByRole("alert")
    .filter({ hasText: "couldn't be loaded" });
  await expect(alert).toBeVisible();
  api.store.buyer.push(item({ value: { portions: 80 } }));
  api.listFailures.remaining = 0;
  await alert.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("80 portions")).toBeVisible();
});

test("adding a preference validates input and succeeds only after the server confirms", async ({
  page,
}) => {
  const api = await mockApi(page);
  await page.goto("/settings/preferences");
  await page.getByRole("button", { name: "Add memory" }).click();
  await expect(page.getByLabel("What is it about?")).toBeFocused();

  await page.getByRole("button", { name: "Save memory" }).click();
  await expect(
    page.getByText("Choose what the memory is about."),
  ).toBeVisible();

  await page
    .getByLabel("What is it about?")
    .selectOption({ label: "Usual portions" });
  await page.getByLabel("Everyone using the demo-hotel buyer account").check();
  await page.getByRole("textbox", { name: "Portions" }).fill("0");
  await page.getByRole("button", { name: "Save memory" }).click();
  await expect(
    page.getByText("Enter a whole number from 1 to 10,000."),
  ).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Portions" })).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  expect(api.writes).toHaveLength(0);

  // A failed write keeps the form and never shows the item as saved.
  await page.getByRole("textbox", { name: "Portions" }).fill("150");
  api.fail.next = {
    status: 503,
    code: "UNAVAILABLE",
    message: "Service unavailable.",
  };
  await page.getByRole("button", { name: "Save memory" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Service unavailable." }),
  ).toBeVisible();
  await expect(page.getByText("150 portions")).toHaveCount(0);
  await expect(
    page.getByRole("status").filter({ hasText: "saved" }),
  ).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Portions" })).toHaveValue(
    "150",
  );

  await page.getByRole("button", { name: "Save memory" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Usual portions saved to Shared with buyer.",
  );
  await expect(page).toHaveURL(/scope=buyer/);
  await expect(page.getByText("150 portions")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add memory" })).toBeFocused();

  expect(api.writes).toHaveLength(2);
  const [failed, saved] = api.writes;
  expect(saved.headers["x-csrf-token"]).toBe("test-csrf");
  expect(saved.body).toMatchObject({
    scope: "buyer",
    key: "default.portions",
    value: { portions: 150 },
  });
  // Retrying the same content reuses its idempotency key.
  expect(saved.body.idempotency_key).toBe(failed.body.idempotency_key);
  expect(Object.keys(saved.body).sort()).toEqual(
    ["idempotency_key", "key", "scope", "value"].sort(),
  );

  // A fixed key that already exists here can't be added twice.
  await page.getByRole("button", { name: "Add memory" }).click();
  await page.getByLabel("Everyone using the demo-hotel buyer account").check();
  await expect(
    page.getByRole("option", { name: "Usual portions (already saved)" }),
  ).toBeDisabled();
});

test("a pack-size preference maps to a supported key and typed value", async ({
  page,
}) => {
  const api = await mockApi(page);
  await page.goto("/settings/preferences");
  await page.getByRole("button", { name: "Add memory" }).click();
  await page
    .getByLabel("What is it about?")
    .selectOption({ label: "Preferred pack size" });
  await page.getByLabel("Ingredient").fill("Kerma (vispi)");
  await page.getByLabel("Pack amount").fill("1,5");
  await page.getByLabel("Unit").fill("L");
  await page.getByLabel("Description (optional)").fill("Weekday lunch");
  await page.getByRole("button", { name: "Save memory" }).click();
  await expect(page.getByText("Kerma (vispi): 1,5 L")).toBeVisible();
  expect(api.writes[0].body).toMatchObject({
    scope: "self",
    key: "preference.pack_size.kerma_vispi",
    value: { ingredient: "Kerma (vispi)", amount: "1.5", unit: "L" },
    description: "Weekday lunch",
  });
});

test("editing sends the expected revision and keeps the draft on conflict", async ({
  page,
}) => {
  const portions = item({ value: { portions: 200 }, revision: 3 });
  const api = await mockApi(page, { buyer: [portions] });
  await page.goto("/settings/preferences?scope=buyer");
  await page.getByRole("button", { name: "Edit Usual portions" }).click();
  const input = page.getByRole("textbox", { name: "Portions" });
  await expect(input).toBeFocused();
  await expect(input).toHaveValue("200");

  // Someone else changes it meanwhile.
  api.store.buyer[0] = {
    ...portions,
    value: { portions: 250 },
    revision: 4,
  };
  await input.fill("180");
  await page.getByRole("button", { name: "Save changes" }).click();
  const conflict = page
    .getByRole("alert")
    .filter({ hasText: "changed elsewhere" });
  await expect(conflict).toBeVisible();
  await expect(input).toHaveValue("180");
  await expect(page.getByText("180 portions")).toHaveCount(0);
  expect(api.writes[0].body.expected_revision).toBe(3);

  await conflict.getByRole("button", { name: "Load latest version" }).click();
  await expect(input).toHaveValue("250");
  await input.fill("175");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("status")).toHaveText("Usual portions updated.");
  await expect(page.getByText("175 portions")).toBeVisible();
  expect(api.writes[1].body.expected_revision).toBe(4);
  await expect(
    page.getByRole("button", { name: "Edit Usual portions" }),
  ).toBeFocused();

  // Escape cancels an edit without writing.
  await page.getByRole("button", { name: "Edit Usual portions" }).click();
  await page.getByRole("textbox", { name: "Portions" }).fill("1");
  await page.keyboard.press("Escape");
  await expect(page.getByText("175 portions")).toBeVisible();
  expect(api.writes).toHaveLength(2);
});

test("forgetting removes the item only after the server confirms", async ({
  page,
}) => {
  const note = item({
    kind: "instruction",
    key: "instruction.short",
    value: { text: "Keep replies short." },
    revision: 2,
  });
  const api = await mockApi(page, { buyer: [note] });
  await page.goto("/settings/preferences?scope=buyer");
  await page
    .getByRole("button", { name: "Forget Assistant instruction" })
    .click();
  await expect(
    page.getByText("doesn't delete any conversation or purchase history", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Keep it" })).toBeFocused();
  await expect(page.getByRole("button", { name: /undo/i })).toHaveCount(0);

  api.fail.next = {
    status: 503,
    code: "UNAVAILABLE",
    message: "Service unavailable.",
  };
  await page.getByRole("button", { name: "Forget memory" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Service unavailable." }),
  ).toBeVisible();
  await expect(page.getByText("Keep replies short.")).toBeVisible();

  await page.getByRole("button", { name: "Forget memory" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Assistant instruction forgotten.",
  );
  await expect(page.getByText("Keep replies short.")).toHaveCount(0);
  await expect(
    page.getByText("No memories yet", { exact: false }),
  ).toBeVisible();
  expect(api.writes.at(-1)).toMatchObject({
    url: `/api/memories/${note.id}/delete`,
    body: { expected_revision: 2 },
  });
  expect(api.writes[0].body.idempotency_key).toBe(
    api.writes[1].body.idempotency_key,
  );
});

test("session expiry signs out and the next sign-in reloads fresh lists", async ({
  page,
}) => {
  const api = await mockApi(page, {
    self: [
      item({
        scope: "user",
        kind: "instruction",
        key: "instruction.private",
        value: { text: "Personal instruction" },
      }),
    ],
  });
  await page.goto("/settings/preferences");
  await expect(page.getByText("Personal instruction")).toBeVisible();

  api.expireSession();
  await page
    .getByRole("button", { name: "Edit Assistant instruction" })
    .click();
  await page.getByRole("textbox", { name: "Instruction" }).fill("Changed");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText("Personal instruction")).toHaveCount(0);

  const before = api.lists.length;
  await page.getByLabel("Username").fill("buyer");
  await page.getByLabel("Password").fill("fixture-password");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/settings\/preferences$/);
  await expect(page.getByText("Personal instruction")).toBeVisible();
  expect(api.lists.length).toBeGreaterThan(before);
  // Nothing about saved memory is kept in browser storage.
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }));
  expect(stored).not.toContain("Personal instruction");
});

test("preferences are reachable from the sidebar and chat, beside Account Settings", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto("/");
  await page
    .getByRole("complementary", { name: "Sidebar" })
    .getByRole("link", { name: "Memory" })
    .click();
  await expect(page).toHaveURL(/\/settings\/preferences$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Memory" }),
  ).toBeVisible();

  await page.goto("/request");
  await page.getByRole("main").getByRole("link", { name: "Memory" }).click();
  await expect(page).toHaveURL(/\/settings\/preferences$/);

  // Purchasing policy settings stay a separate screen and link.
  const sidebar = page.getByRole("complementary", { name: "Sidebar" });
  await expect(
    sidebar.getByRole("link", { name: "Account Settings" }),
  ).toHaveAttribute("href", "/settings");
  await expect(sidebar.getByRole("link", { name: "Memory" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(
    sidebar.getByRole("link", { name: "Account Settings" }),
  ).not.toHaveAttribute("aria-current", "page");
});

test("mobile layout fits the viewport and tabs work from the keyboard", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await mockApi(page, {
    buyer: [
      item({
        kind: "preference",
        key: "preference.product.cream",
        value: {
          ingredient: "Cream",
          preference:
            "Prefer Finnish organic cream in recyclable cartons whenever available.",
          product_ids: [],
        },
      }),
    ],
  });
  await page.goto("/settings/preferences");
  const width = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(width.scroll).toBeLessThanOrEqual(width.client);

  await page.getByRole("tab", { name: "Personal" }).focus();
  await page.keyboard.press("ArrowRight");
  const buyerTab = page.getByRole("tab", { name: "Shared with buyer" });
  await expect(buyerTab).toBeFocused();
  await expect(buyerTab).toHaveAttribute("aria-selected", "true");
  await expect(
    page.getByText("Prefer Finnish organic cream", { exact: false }),
  ).toBeVisible();

  // The mobile menu links to the screen too.
  await page.getByRole("button", { name: "Open menu" }).click();
  await page
    .getByRole("dialog", { name: "Menu" })
    .getByRole("link", { name: "Memory" })
    .click();
  await expect(page.getByRole("dialog", { name: "Menu" })).toHaveCount(0);
});
