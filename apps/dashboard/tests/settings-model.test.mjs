import assert from "node:assert/strict";
import test from "node:test";

const m = await import("../lib/settings-model.ts");

test("ciApiUrl derives the API origin from the configured base", () => {
  assert.equal(m.ciApiUrl("https://radius.example.test"), "https://radius.example.test");
  assert.equal(m.ciApiUrl("https://radius.example.test/"), "https://radius.example.test");
  assert.equal(m.ciApiUrl("https://radius.example.test/api/v1/"), "https://radius.example.test");
  assert.equal(m.ciApiUrl("http://localhost:8000"), "http://localhost:8000");
  assert.equal(m.ciApiUrl(""), "");
  assert.equal(m.ciApiUrl(undefined), "");
  assert.equal(m.ciApiUrl("not a url"), "");
  assert.equal(m.ciApiUrl("javascript:alert(1)"), "");
});

test("ciUploadEndpoint appends the versioned prefix once", () => {
  assert.equal(m.ciUploadEndpoint("https://radius.example.test"), "https://radius.example.test/api/v1");
  assert.equal(m.ciUploadEndpoint("https://radius.example.test/api/v1"), "https://radius.example.test/api/v1");
  assert.equal(m.ciUploadEndpoint(""), "");
});

test("the workflow snippet uses the upload action with secrets, not literal values", () => {
  const snippet = m.uploadWorkflowSnippet();
  assert.match(snippet, /actions\/upload-results@/);
  assert.match(snippet, /api-url: \$\{\{ vars\.RADIUS_API_URL \}\}/);
  assert.match(snippet, /organization-id: \$\{\{ secrets\.RADIUS_ORG_ID \}\}/);
  assert.match(snippet, /api-key: \$\{\{ secrets\.RADIUS_API_KEY \}\}/);
  assert.match(snippet, /if: \$\{\{ !cancelled\(\) \}\}/);
  assert.doesNotMatch(snippet, /rdk_/);
  assert.equal(m.UPLOAD_KEY_SCOPE, "ci-upload");
});
