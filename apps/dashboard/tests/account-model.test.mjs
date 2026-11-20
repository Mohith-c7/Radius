import assert from "node:assert/strict";
import test from "node:test";
import { initials, paginationTotal, profileRows, roleLabel } from "../lib/account-model.ts";

const user = {
  id: "u-1",
  name: "Ada Lovelace",
  email: "ada@example.test",
  email_verified: true,
  role: "admin",
  organization_id: "11111111-1111-4111-8111-111111111111",
};

test("profile rows come from the signed-in user, nothing else", () => {
  assert.deepEqual(profileRows(user), [
    { label: "Name", value: "Ada Lovelace" },
    { label: "Email", value: "ada@example.test" },
    { label: "Email verified", value: "Yes" },
    { label: "Role", value: "Admin" },
    { label: "Organization ID", value: "11111111-1111-4111-8111-111111111111" },
  ]);
});

test("missing name, unverified email and no organization are shown honestly", () => {
  const rows = profileRows({ ...user, name: "  ", email_verified: false, organization_id: null });
  const byLabel = Object.fromEntries(rows.map((row) => [row.label, row.value]));
  assert.equal(byLabel["Name"], "Not set");
  assert.equal(byLabel["Email verified"], "No");
  assert.equal(byLabel["Organization ID"], "Not assigned");
  const withoutField = profileRows({ ...user, organization_id: undefined });
  assert.equal(withoutField.at(-1).value, "Not assigned");
});

test("initials use up to two name parts, then the email, then a placeholder", () => {
  assert.equal(initials("Ada Lovelace", "ada@example.test"), "AL");
  assert.equal(initials("ada augusta king", null), "AA");
  assert.equal(initials("Mononym"), "M");
  assert.equal(initials("", "zed@example.test"), "Z");
  assert.equal(initials(undefined, ""), "?");
});

test("role labels are capitalised and an empty role is not dressed up", () => {
  assert.equal(roleLabel("developer"), "Developer");
  assert.equal(roleLabel("org_owner"), "Org owner");
  assert.equal(roleLabel(""), "Not set");
  assert.equal(roleLabel(undefined), "Not set");
});

test("paginationTotal reads meta.pagination.total and falls back otherwise", () => {
  assert.equal(paginationTotal({ pagination: { limit: 1, offset: 0, total: 42, returned: 1 } }, 1), 42);
  assert.equal(paginationTotal({ pagination: { total: 0 } }, 5), 0);
  assert.equal(paginationTotal({}, 3), 3);
  assert.equal(paginationTotal(undefined, 3), 3);
  assert.equal(paginationTotal({ pagination: { total: "42" } }, 1), 1);
  assert.equal(paginationTotal({ pagination: { total: -1 } }, 1), 1);
});
