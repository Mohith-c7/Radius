import assert from "node:assert/strict";
import test, { afterEach } from "node:test";

process.env.NEXT_PUBLIC_RADIUS_API_BASE_URL = "https://radius.test/";
process.env.RADIUS_DASHBOARD_INTERNAL_URL = "http://dashboard.test";
process.env.NEXT_PUBLIC_RADIUS_ORGANIZATION_ID =
  "11111111-1111-4111-8111-111111111111";

const api = await import("../lib/api.ts");
const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function envelope(data, init = {}) {
  return new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
    status: init.status ?? 200,
  });
}

test("listRepositories calls the same-origin proxy without credentials", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), "http://dashboard.test/api/radius/repositories");
    assert.equal(init?.cache, "no-store");

    const headers = new Headers(init?.headers);
    // Credentials are attached by the server-side proxy, never by the browser.
    assert.equal(headers.get("X-Radius-API-Key"), null);

    return envelope({ success: true, data: [] });
  };

  assert.deepEqual(await api.listRepositories(), []);
});

test("listAnalyses preserves supported filters as query parameters", async () => {
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    assert.equal(url.pathname, "/api/radius/analyses");
    assert.equal(url.searchParams.get("repositoryId"), "repo-1");
    assert.equal(url.searchParams.get("status"), "completed");
    assert.equal(url.searchParams.has("pullRequestId"), false);

    return envelope({ success: true, data: [] });
  };

  assert.deepEqual(
    await api.listAnalyses({ repositoryId: "repo-1", status: "completed" }),
    [],
  );
});

test("connectRepository posts JSON with an idempotency key", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), "http://dashboard.test/api/radius/repositories");
    assert.equal(init?.method, "POST");

    const headers = new Headers(init?.headers);
    assert.equal(headers.get("Content-Type"), "application/json");
    assert.match(headers.get("Idempotency-Key") ?? "", /^[\da-f-]{36}$/i);

    assert.deepEqual(JSON.parse(String(init?.body)), {
      organizationId: "11111111-1111-4111-8111-111111111111",
      repositoryId: 123,
      name: "Radius",
      owner: "Mohith-c7",
      defaultBranch: "develop",
      cloneUrl: "https://github.com/Mohith-c7/Radius.git",
      visibility: "private",
    });

    return envelope({
      success: true,
      data: {
        id: "repo-1",
        organization_id: "11111111-1111-4111-8111-111111111111",
        github_repository_id: 123,
        name: "Radius",
        owner: "Mohith-c7",
        full_name: "Mohith-c7/Radius",
        provider: "github",
        default_branch: "develop",
        clone_url: "https://github.com/Mohith-c7/Radius.git",
        visibility: "private",
        status: "connected",
      },
    });
  };

  const repository = await api.connectRepository({
    organizationId: "11111111-1111-4111-8111-111111111111",
    repositoryId: 123,
    name: "Radius",
    owner: "Mohith-c7",
    defaultBranch: "develop",
    cloneUrl: "https://github.com/Mohith-c7/Radius.git",
    visibility: "private",
  });

  assert.equal(repository.full_name, "Mohith-c7/Radius");
});

test("radiusFetch surfaces backend envelope errors", async () => {
  globalThis.fetch = async () =>
    envelope(
      {
        success: false,
        data: null,
        error: {
          code: "ACCESS_DENIED",
          message: "Organization header is invalid.",
        },
      },
      { status: 403 },
    );

  await assert.rejects(
    api.listRepositories(),
    /Organization header is invalid\./,
  );
});

test("radiusFetch rejects successful empty data envelopes", async () => {
  globalThis.fetch = async () => envelope({ success: true, data: null });

  await assert.rejects(
    api.getAnalysis("analysis-1"),
    /Radius API returned an empty data payload\./,
  );
});

test("getTestRunResult fetches CI test run results", async () => {
  globalThis.fetch = async (input) => {
    assert.equal(
      String(input),
      "http://dashboard.test/api/radius/analyses/analysis-1/tests/results",
    );
    return envelope({
      success: true,
      data: {
        id: "result-1",
        analysis_id: "analysis-1",
        status: "PASSED",
        total_tests: 10,
        passed: 10,
        failed: 0,
        skipped: 0,
        duration_ms: 125,
        output: "",
      },
    });
  };

  const result = await api.getTestRunResult("analysis-1");
  assert.equal(result?.status, "PASSED");
  assert.equal(result?.total_tests, 10);
});

test("uploadTestResults posts JUnit XML report payload", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(
      String(input),
      "http://dashboard.test/api/radius/analyses/analysis-1/tests/results?commit_sha=abc123def456",
    );
    assert.equal(init?.method, "POST");
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("Content-Type"), "application/xml");
    assert.equal(init?.body, "<testsuite></testsuite>");

    return envelope({
      success: true,
      data: {
        id: "result-2",
        analysis_id: "analysis-1",
        status: "PASSED",
        total_tests: 1,
        passed: 1,
        failed: 0,
        skipped: 0,
        duration_ms: 50,
        output: "",
      },
    });
  };

  const res = await api.uploadTestResults("analysis-1", "<testsuite></testsuite>", true, "abc123def456");
  assert.equal(res.status, "PASSED");
  assert.equal(res.total_tests, 1);
});


test("uploadTestResults refuses to upload without a commit to bind the results to", async () => {
  let called = false;
  globalThis.fetch = async () => {
    called = true;
    return envelope({ success: true, data: {} });
  };
  await assert.rejects(() => api.uploadTestResults("analysis-1", "<x/>", true, "  "), /no commit/);
  assert.equal(called, false);
});

test("testResultsUploadPath encodes the commit and trims it", () => {
  assert.equal(
    api.testResultsUploadPath("analysis-1", " abc&x=1 "),
    "/analyses/analysis-1/tests/results?commit_sha=abc%26x%3D1",
  );
});
