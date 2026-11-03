import assert from "node:assert/strict";
import test from "node:test";

const { postSignupPath } = await import("../lib/post-signup.ts");

test("a verified, signed-in account goes to the dashboard", () => {
  assert.equal(postSignupPath({ email_verified: true }), "/");
});

test("an unverified account is asked to check its email", () => {
  assert.equal(postSignupPath({ email_verified: false }), "/verify-email");
});

test("a missing user falls back to the verification page, never the dashboard", () => {
  assert.equal(postSignupPath(null), "/verify-email");
  assert.equal(postSignupPath(undefined), "/verify-email");
});
