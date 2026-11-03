import assert from "node:assert/strict";
import test from "node:test";

const v = await import("../lib/verify-email.ts");

test("the password rule matches the API rule", () => {
  assert.equal(v.passwordIsValid("Abcdef12"), true);
  for (const bad of ["abcdef12", "ABCDEF12", "Abcdefgh", "Ab1", ""]) assert.equal(v.passwordIsValid(bad), false, bad);
});

test("the form is validated before anything is sent", () => {
  assert.equal(v.validateNewPassword("Abcdef12", "Abcdef12"), null);
  assert.equal(v.validateNewPassword("Abcdef12", "Abcdef13"), "Passwords do not match.");
  assert.equal(v.validateNewPassword("abc", "abc"), v.PASSWORD_RULE_MESSAGE);
});

test("the request body carries the password only when the API asked for one", () => {
  assert.deepEqual(JSON.parse(v.verifyEmailBody("tok", true, "Abcdef12")), { token: "tok", password: "Abcdef12" });
  assert.deepEqual(JSON.parse(v.verifyEmailBody("tok", false, "Abcdef12")), { token: "tok" });
});

test("only a well-formed check answer is trusted", () => {
  assert.equal(v.isVerifyCheck({ password_required: true }), true);
  assert.equal(v.isVerifyCheck({ password_required: false }), true);
  for (const bad of [null, {}, { password_required: "yes" }, "x", 1]) assert.equal(v.isVerifyCheck(bad), false);
});
