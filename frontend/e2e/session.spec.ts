import { expect, test, type Page } from "@playwright/test";

// Buyer session path: sign in, failed-login error, session restore on reload,
// sign out. Mocked at the browser<->API edge, matching chat.spec.ts prior art.
// The real contract (cookie session + CSRF token, status codes, error shape)
// is verified separately against the running backend; see docs/pre-existing-work.md.

const session = {
  username: "buyer",
  buyer_id: "demo-hotel",
  csrf_token: "test-csrf-token",
};

async function mockUnauthenticated(page: Page) {
  await page.route("**/api/session", (route) =>
    route.fulfill({
      status: 401,
      json: {
        error: {
          code: "UNAUTHENTICATED",
          message: "Sign in to continue your purchase.",
        },
      },
    }),
  );
  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );
}

async function mockAuthenticated(page: Page) {
  let authenticated = true;
  await page.route("**/api/session", (route) =>
    route.fulfill({
      status: authenticated ? 200 : 401,
      json: authenticated
        ? session
        : {
            error: {
              code: "UNAUTHENTICATED",
              message: "Sign in to continue your purchase.",
            },
          },
    }),
  );
  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );
  const logoutCalls: Array<Record<string, string>> = [];
  await page.route("**/api/logout", async (route) => {
    logoutCalls.push(route.request().headers());
    authenticated = false;
    await route.fulfill({ status: 204 });
  });
  return { logoutCalls };
}

test("bad credentials show a clear error and keep the buyer on sign-in", async ({
  page,
}) => {
  await mockUnauthenticated(page);
  await page.route("**/api/login", async (route) => {
    await route.fulfill({
      status: 401,
      json: {
        error: {
          code: "LOGIN_FAILED",
          message: "Username or password is incorrect.",
        },
      },
    });
  });
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Username").fill("buyer");
  await page.getByLabel("Password", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Username or password is incorrect.",
  );
  await expect(page).toHaveURL(/\/login$/);
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
});

test("sign-in succeeds and yields a usable session", async ({ page }) => {
  await mockUnauthenticated(page);
  const loginBodies: Array<Record<string, unknown>> = [];
  await page.route("**/api/login", async (route) => {
    loginBodies.push(route.request().postDataJSON());
    await route.fulfill({ json: session });
  });
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Username").fill("buyer");
  await page.getByLabel("Password", { exact: true }).fill("correct-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByRole("heading", { name: "What are we cooking?" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  expect(loginBodies).toEqual([
    { username: "buyer", password: "correct-password" },
  ]);
});

test("a valid session restores automatically on reload", async ({ page }) => {
  await mockAuthenticated(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "What are we cooking?" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByRole("heading", { name: "What are we cooking?" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
});

test("sign-out clears the session and a later reload requires login again", async ({
  page,
}) => {
  const { logoutCalls } = await mockAuthenticated(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(logoutCalls).toHaveLength(1);
  expect(logoutCalls[0]["x-csrf-token"]).toBe(session.csrf_token);
  await page.reload();
  await expect(page).toHaveURL(/\/login$/);
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
});
