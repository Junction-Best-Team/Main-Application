import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { execFileSync } from "node:child_process";

// Opt in against a running fixture-mode app and the same PostgreSQL database.
// Fast UI-only regression checks live in chat.spec.ts and need no credentials.
test.skip(
  process.env.AIMO_INTEGRATION !== "1",
  "Set AIMO_INTEGRATION=1 for live app/database browser checks.",
);
const env = fs.existsSync("../.env")
  ? Object.fromEntries(
      fs
        .readFileSync("../.env", "utf8")
        .split("\n")
        .filter((l) => l && !l.startsWith("#"))
        .map((l) => {
          const i = l.indexOf("=");
          return [l.slice(0, i), l.slice(i + 1)];
        }),
    )
  : process.env;

test("historical approval stays superseded and links to committed terms", async ({
  page,
}) => {
  const fixture = JSON.parse(
    execFileSync("uv", ["run", "python", "tests/browser_revision_fixture.py"], {
      cwd: "..",
      encoding: "utf8",
    }),
  );
  await page.goto(`/approvals/${fixture.approval_id}`);
  await page.getByLabel("Username").fill("buyer");
  await page
    .getByLabel("Password", { exact: true })
    .fill(env.DEMO_BUYER_PASSWORD || "");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator(".purchase-sheet")).toContainText("1,700.00");
  await expect(page.locator(".status-note")).toContainText("Superseded");
  await expect(
    page.getByRole("button", { name: "Confirm purchase" }),
  ).toHaveCount(0);
  await page.getByRole("link", { name: "View current revision 2" }).click();
  await expect(page).toHaveURL(
    new RegExp(`/purchases/${fixture.proposal_id}$`),
  );
  await expect(page.locator(".purchase-sheet")).toContainText("1,870.00");
  await expect(page.locator(".purchase-row")).toContainText("Accepted (demo)");
  await page.reload();
  await expect(page.locator(".purchase-sheet")).toContainText("1,870.00");
});

test("removed external interfaces return API errors instead of frontend HTML", async ({
  request,
}) => {
  for (const path of [
    "/mcp",
    "/mcp/",
    "/api/agent/commit_order",
    "/api/not-a-route",
  ]) {
    const response = await request.get(path);
    expect(response.status()).toBe(404);
    expect(response.headers()["content-type"]).toContain("application/json");
  }
});
