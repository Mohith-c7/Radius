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

test("the workflow snippet matches radius-evidence.yml and the upload action inputs", () => {
  const snippet = m.uploadWorkflowSnippet();
  assert.match(
    snippet,
    /uses: Mohith-c7\/Radius\/actions\/upload-results@1099949af42ce60ccdc8cdd122bbebc9fe15f692 # v0\.1\.1/,
  );
  assert.match(snippet, /api-url: \$\{\{ vars\.RADIUS_API_URL \}\}/);
  assert.match(snippet, /organization-id: \$\{\{ vars\.RADIUS_ORGANIZATION_ID \}\}/);
  assert.match(snippet, /api-key: \$\{\{ secrets\.RADIUS_CI_UPLOAD_KEY \}\}/);
  assert.match(snippet, /wait-seconds: "900"/);
  assert.doesNotMatch(snippet, /RADIUS_ORG_ID|secrets\.RADIUS_API_KEY|@develop/);
  assert.match(snippet, /if: \$\{\{ !cancelled\(\) \}\}/);
  assert.doesNotMatch(snippet, /rdk_/);
  assert.equal(m.UPLOAD_KEY_SCOPE, "ci-upload");
});
