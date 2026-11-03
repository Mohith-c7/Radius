import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// Source guard (the repo has no browser unit tests): after a successful password sign-in the form must do a
// full navigation. router.replace("/") reused a cached redirect to /login that the client router stored while
// the user was signed out, so sign-in succeeded (200) but the page never left /login (found in a real browser).
const source = readFileSync(new URL("../components/auth-forms.tsx", import.meta.url), "utf8");
const loginForm = source.slice(source.indexOf("export function LoginForm"), source.indexOf("export function SignupForm"));

test("the login form navigates with a full page load after a successful sign-in", () => {
  assert.ok(loginForm.length > 200, "LoginForm source found");
  assert.match(loginForm, /await refresh\(\);\s*[\s\S]*window\.location\.assign\("\/"\)/);
  assert.doesNotMatch(loginForm, /router\.replace\("\/"\)/);
});
