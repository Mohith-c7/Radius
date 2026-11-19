import assert from "node:assert/strict";
import test from "node:test";

const { demoSignInEnabled } = await import("../lib/demo-signin.ts");

test("the demo sign-in button is hidden in a production build by default", () => {
  assert.equal(demoSignInEnabled(undefined, "production"), false);
  assert.equal(demoSignInEnabled("", "production"), false);
  assert.equal(demoSignInEnabled("false", "production"), false);
  assert.equal(demoSignInEnabled("1", "production"), false);
});

test("the dev compose build flag shows it", () => {
  assert.equal(demoSignInEnabled("true", "production"), true);
  assert.equal(demoSignInEnabled(" TRUE ", "production"), true);
});

test("next dev shows it", () => {
  assert.equal(demoSignInEnabled(undefined, "development"), true);
  assert.equal(demoSignInEnabled(undefined, "test"), false);
});
