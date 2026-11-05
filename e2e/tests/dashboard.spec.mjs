// Drives a running Radius stack (dev override: accounts are auto-verified) through the browser:
// sign up -> dashboard -> main pages -> sign out -> sign in. It fails on page errors, console
// errors and HTTP 4xx/5xx responses, except the documented ones in ALLOWED_RESPONSES.
import { expect, test } from "@playwright/test";
import fs from "node:fs";
import crypto from "node:crypto";

const SHOTS = "screenshots";
fs.mkdirSync(SHOTS, { recursive: true });

// Documented, expected error responses. Anything else is a failure.
//   GET /auth/me -> 401 : the session probe every page makes before sign-in and after sign-out.
const ALLOWED_RESPONSES = [{ method: "GET", status: 401, pathEnds: "/api/v1/auth/me" }];

const isAllowed = (method, status, url) =>
  ALLOWED_RESPONSES.some(
    (a) => a.method === method && a.status === status && new URL(url).pathname.endsWith(a.pathEnds),
  );

// Credentials are generated at run time; nothing secret is committed.
const suffix = crypto.randomBytes(5).toString("hex");
const email = `e2e+${suffix}@example.com`;
const password = `Aa1${crypto.randomBytes(9).toString("hex")}`;

test("sign up, browse the dashboard, sign out and sign in", async ({ page }) => {
  const problems = [];
  page.on("pageerror", (error) => problems.push(`pageerror: ${String(error).slice(0, 300)}`));
  page.on("console", (message) => {
    // "Failed to load resource" lines mirror the HTTP responses checked below.
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) {
      problems.push(`console.error: ${message.text().slice(0, 300)}`);
    }
  });
  page.on("response", (response) => {
    const status = response.status();
    const method = response.request().method();
    if (status >= 400 && !isAllowed(method, status, response.url())) {
      problems.push(`HTTP ${status} ${method} ${response.url().slice(0, 200)}`);
    }
  });
  // The dashboard uses a system font stack and must not contact any font host. Abort such
  // requests (so the test never waits on the network) and record them; the end of the test
  // asserts there were none.
  const FONT_HOSTS = new Set(["fonts.googleapis.com", "fonts.gstatic.com"]);
  const fontRequests = [];
  await page.route(
    (url) => FONT_HOSTS.has(url.hostname),
    (route) => {
      fontRequests.push(route.request().url());
      return route.abort();
    },
  );
  const shot = (name) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
  const heading = (name) => expect(page.getByRole("heading", { level: 1, name })).toBeVisible();

  // Unauthenticated visitors are sent to the login page.
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await shot("01-login");

  // Sign up. In the dev stack the account is auto-verified and signed in, so the app must go to
  // the dashboard and must NOT show "Check your email".
  await page.goto("/signup");
  await page.getByLabel("Name", { exact: true }).fill("E2E Tester");
  await page.getByLabel("Email").fill(email);
  await page.locator("#new-password").fill(password);
  await page.locator("#confirm-password").fill(password);
  await page.locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page).toHaveURL(/\/$/);
  await heading("Engineering workspace");
  await expect(page.getByText("Check your email")).toHaveCount(0);
  // Regression: the home page used to be reported as never becoming network-idle.
  await page.waitForLoadState("networkidle", { timeout: 20_000 });
  await shot("02-dashboard");

  for (const [path, title] of [
    ["/pull-requests", "Pull requests"],
    ["/repositories", "Repositories"],
    ["/analyses", "Analyses"],
    ["/settings", "Settings"],
    ["/help", "Help & support"],
  ]) {
    await page.goto(path);
    await heading(title);
    await expect(page.getByText("Dashboard could not reach the Radius API.")).toHaveCount(0);
    await shot(`03${path.replaceAll("/", "-")}`);
  }

  // Sign out, then sign in again with the same account.
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await heading("Engineering workspace");
  await shot("04-signed-in-again");

  expect(fontRequests, "no request may go to a font host").toEqual([]);
  expect(problems, problems.join("\n")).toEqual([]);
});
