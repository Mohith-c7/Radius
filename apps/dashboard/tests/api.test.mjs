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
    assert.equal(String(input), "http://dashboard.test/api/radius/repositories?limit=500");
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
    assert.equal(url.searchParams.get("limit"), "500"); // API lists are paginated (max 500)
    assert.equal(url.searchParams.has("offset"), false);

    return envelope({ success: true, data: [] });
  };

  assert.deepEqual(
    await api.listAnalyses({ repositoryId: "repo-1", status: "completed" }),
    [],
  );
});

test("countAnalyses asks for one row and reports the pagination total", async () => {
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    assert.equal(url.pathname, "/api/radius/analyses");
    assert.equal(url.searchParams.get("limit"), "1");
    return new Response(
      JSON.stringify({
        success: true,
        data: [{ id: "a-1" }],
        meta: { pagination: { limit: 1, offset: 0, total: 37, returned: 1 } },
      }),
      { headers: { "Content-Type": "application/json" }, status: 200 },
    );
  };

  assert.equal(await api.countAnalyses(), 37);
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

test("getTestRunResult maps 404 (no CI upload yet) to null", async () => {
  globalThis.fetch = async () =>
    envelope(
      { success: false, data: null, error: { code: "NOT_FOUND", message: "No test results" } },
      { status: 404 },
    );
  assert.equal(await api.getTestRunResult("analysis-1"), null);
});

test("getReadiness reports the /ready status through the proxy", async () => {
  globalThis.fetch = async (input) => {
    assert.equal(String(input), "http://dashboard.test/api/radius/ready");
    return envelope({ success: false, data: null }, { status: 503 });
  };
  assert.deepEqual(await api.getReadiness(), { status: 503 });
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

test("startAnalysis sends no pull_request_id for a manual branch/commit analysis", async () => {
  let sent = null;
  globalThis.fetch = async (input, init) => {
    assert.equal(new URL(String(input)).pathname, "/api/radius/analyses");
    sent = JSON.parse(String(init?.body));
    return envelope({ success: true, data: { id: "a-1", pull_request_id: null } }, { status: 202 });
  };

  const analysis = await api.startAnalysis({ repositoryId: "repo-1", commitSha: " abc1234 " });
  assert.equal(analysis.id, "a-1");
  assert.deepEqual(sent, { repository_id: "repo-1", commit_sha: "abc1234" });
  assert.equal("pull_request_id" in sent, false);
});

test("startAnalysisBody only sends a real pull request id", () => {
  assert.deepEqual(api.startAnalysisBody({ repositoryId: "r", commitSha: "abc", pullRequestId: null }), {
    repository_id: "r",
    commit_sha: "abc",
  });
  assert.deepEqual(api.startAnalysisBody({ repositoryId: "r", commitSha: "abc", pullRequestId: "  " }), {
    repository_id: "r",
    commit_sha: "abc",
  });
  assert.deepEqual(api.startAnalysisBody({ repositoryId: "r", commitSha: "abc", pullRequestId: "pr-1" }), {
    repository_id: "r",
    commit_sha: "abc",
    pull_request_id: "pr-1",
  });
});

function plainText(text, status) {
  return new Response(text, { status, headers: { "Content-Type": "text/plain; charset=utf-8" } });
}

test("a plain-text 500 becomes a readable error, never a JSON parse error", async () => {
  globalThis.fetch = async () => plainText("Internal Server Error", 500);
  await assert.rejects(
    () => api.startAnalysis({ repositoryId: "repo-1", commitSha: "abc1234" }),
    (error) => {
      assert.equal(error.message, "Radius API error (HTTP 500). Try again.");
      assert.equal(error.status, 500);
      assert.doesNotMatch(error.message, /JSON|Unexpected token/);
      return true;
    },
  );
  globalThis.fetch = async () => plainText("<html>Bad gateway</html>", 502);
  await assert.rejects(() => api.radiusRequest("/analyses"), /Radius API error \(HTTP 502\)\. Try again\./);
  globalThis.fetch = async () => plainText("", 503);
  await assert.rejects(() => api.getAnalysis("a-1"), /Radius API error \(HTTP 503\)\. Try again\./);
});

test("error messages come from the envelope or a FastAPI validation detail", async () => {
  globalThis.fetch = async () =>
    envelope(
      { success: false, data: null, error: { code: "PULL_REQUEST_NOT_FOUND", message: "Pull request not found." } },
      { status: 404 },
    );
  await assert.rejects(
    () => api.startAnalysis({ repositoryId: "repo-1", commitSha: "abc1234", pullRequestId: "pr-x" }),
    (error) => error.message === "Pull request not found." && error.code === "PULL_REQUEST_NOT_FOUND",
  );
  assert.equal(
    api.apiErrorMessage(422, { detail: [{ loc: ["body", "commitSha"], msg: "String should match pattern" }] }),
    "Invalid request (commitSha): String should match pattern.",
  );
  assert.equal(api.apiErrorMessage(400, { detail: "Bad input" }), "Bad input");
  assert.equal(api.apiErrorMessage(500, { unexpected: true }), "Radius API request failed (HTTP 500).");
  assert.equal(api.apiErrorMessage(500, null), "Radius API error (HTTP 500). Try again.");
});

test("a 200 with an unreadable body is an error, not a crash", async () => {
  globalThis.fetch = async () => plainText("not json", 200);
  await assert.rejects(() => api.listRepositories(), /Radius API error \(HTTP 200\)\. Try again\./);
});
