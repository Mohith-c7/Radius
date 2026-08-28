import assert from "node:assert/strict";
import test, { afterEach } from "node:test";

process.env.NEXT_PUBLIC_RADIUS_API_BASE_URL = "https://radius.test/";
process.env.NEXT_PUBLIC_RADIUS_ORGANIZATION_ID =
  "11111111-1111-4111-8111-111111111111";
process.env.NEXT_PUBLIC_RADIUS_API_KEY = "dashboard-test-key";

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

test("listRepositories sends Radius headers and normalizes API URLs", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), "https://radius.test/api/v1/repositories");
    assert.equal(init?.cache, "no-store");

    const headers = new Headers(init?.headers);
    assert.equal(
      headers.get("X-Radius-Organization-Id"),
      "11111111-1111-4111-8111-111111111111",
    );
    assert.equal(headers.get("X-Radius-API-Key"), "dashboard-test-key");

    return envelope({ success: true, data: [] });
  };

  assert.deepEqual(await api.listRepositories(), []);
});

test("listAnalyses preserves supported filters as query parameters", async () => {
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    assert.equal(url.pathname, "/api/v1/analyses");
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
    assert.equal(String(input), "https://radius.test/api/v1/repositories");
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
