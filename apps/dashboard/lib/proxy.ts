// Server-side helpers for the /api/radius proxy. Pure functions (no Next.js
// imports) so they can be unit tested. The API key never leaves the server.

export const MAX_BODY_BYTES = 5 * 1024 * 1024; // 5 MiB (JUnit XML uploads)

const ID = "[A-Za-z0-9_-]{1,64}";
const ALLOWED: Array<{ pattern: RegExp; methods: readonly string[] }> = [
  { pattern: new RegExp(`^repositories$`), methods: ["GET", "POST"] },
  // Must precede the generic repositories/<id> rule, which would match first.
  { pattern: new RegExp(`^repositories/connect-github$`), methods: ["POST"] },
  { pattern: new RegExp(`^repositories/${ID}$`), methods: ["GET", "PATCH", "DELETE"] },
  { pattern: new RegExp(`^repositories/${ID}/pull-requests$`), methods: ["GET"] },
  { pattern: new RegExp(`^repositories/${ID}/pull-requests/[0-9]{1,9}$`), methods: ["GET"] },
  { pattern: new RegExp(`^repositories/${ID}/sync-pull-requests$`), methods: ["POST"] },
  // Pull-based GitHub (no webhook): connect by owner/name and analyze one PR by number.
  { pattern: new RegExp(`^repositories/${ID}/pull-requests/[0-9]{1,9}/analyze$`), methods: ["POST"] },
  { pattern: new RegExp(`^analyses$`), methods: ["GET", "POST"] },
  { pattern: new RegExp(`^analyses/${ID}$`), methods: ["GET"] },
  { pattern: new RegExp(`^analyses/${ID}/rerun$`), methods: ["POST"] },
  { pattern: new RegExp(`^analyses/${ID}/(blast-radius|confidence|tests|graph)$`), methods: ["GET"] },
  { pattern: new RegExp(`^analyses/${ID}/tests/results$`), methods: ["GET", "POST"] },
  // Verdict v2 alpha (VS-09 / VS-10): this one read-only route. The undocumented
  // /verdict alias and anything below it stay rejected.
  { pattern: new RegExp(`^analyses/${ID}/verdict-v2$`), methods: ["GET"] },
  // Intent API (IN-08 / IN-11): exactly these routes and methods.
  { pattern: new RegExp(`^analyses/${ID}/intent$`), methods: ["GET"] },
  { pattern: new RegExp(`^analyses/${ID}/intent/(snapshots|diff)$`), methods: ["GET"] },
  { pattern: new RegExp(`^analyses/${ID}/intent/snapshots/${ID}$`), methods: ["GET"] },
  { pattern: new RegExp(`^analyses/${ID}/intent/sources$`), methods: ["GET", "POST"] },
  { pattern: new RegExp(`^analyses/${ID}/intent/rebuild$`), methods: ["POST"] },
  { pattern: new RegExp(`^analyses/${ID}/intent/criteria$`), methods: ["POST"] },
  { pattern: new RegExp(`^analyses/${ID}/intent/criteria/${ID}$`), methods: ["PATCH"] },
  { pattern: new RegExp(`^analyses/${ID}/intent/criteria/${ID}/history$`), methods: ["GET"] },
];

export type ProxyConfig = {
  apiBaseUrl: string;
  organizationId: string;
  apiKey: string;
};

export function loadProxyConfig(env: Record<string, string | undefined> = process.env): ProxyConfig {
  return {
    apiBaseUrl:
      env.RADIUS_API_BASE_URL ||
      env.API_BASE_URL ||
      env.NEXT_PUBLIC_RADIUS_API_BASE_URL ||
      "http://localhost:8000",
    organizationId: env.RADIUS_ORGANIZATION_ID || env.NEXT_PUBLIC_RADIUS_ORGANIZATION_ID || "",
    apiKey: env.RADIUS_API_KEY || "",
  };
}

/** Returns the normalized path if the path+method is allowlisted, else null / "method". */
export function checkRoute(segments: string[], method: string): "ok" | "not_found" | "method" {
  if (segments.some((s) => s === "" || s === "." || s === ".." || /[\/%\0]/.test(s))) {
    return "not_found";
  }
  const joined = segments.join("/");
  const rule = ALLOWED.find((r) => r.pattern.test(joined));
  if (!rule) return "not_found";
  return rule.methods.includes(method.toUpperCase()) ? "ok" : "method";
}

// "*" or one or more strong ETags ("<token>"); weak validators are not accepted.
export const IF_MATCH_PATTERN =
  /^(\*|"[A-Za-z0-9_-]{1,128}"(\s*,\s*"[A-Za-z0-9_-]{1,128}"){0,9})$/;
// Same pattern the API enforces for X-Radius-Actor.
export const ACTOR_PATTERN = /^[A-Za-z0-9_.@:+-]{1,128}$/;

function isIntentWrite(segments: string[] | undefined, method: string | undefined): boolean {
  return (
    !!segments &&
    segments[0] === "analyses" &&
    segments[2] === "intent" &&
    ["POST", "PATCH"].includes((method ?? "").toUpperCase())
  );
}

const FORWARDED_CONTENT_TYPES = ["application/json", "application/xml", "text/xml"];

/** Build upstream URL; only the configured base is ever used. */
export function buildUpstreamUrl(config: ProxyConfig, segments: string[], search: string): string {
  const base = config.apiBaseUrl.replace(/\/+$/, "");
  return `${base}/api/v1/${segments.join("/")}${search}`;
}

/**
 * Build upstream headers from scratch (allowlist). Client cookies, Authorization,
 * Host, X-Radius-* and anything else sent by the browser are NOT forwarded.
 */
export function buildUpstreamHeaders(
  config: ProxyConfig,
  incoming: Headers,
  route: { segments?: string[]; method?: string } = {},
): Headers {
  const headers = new Headers();
  headers.set("Accept", "application/json");
  if (config.organizationId) headers.set("X-Radius-Organization-Id", config.organizationId);
  if (config.apiKey) headers.set("X-Radius-API-Key", config.apiKey);
  const idem = incoming.get("idempotency-key");
  if (idem && /^[A-Za-z0-9_-]{8,128}$/.test(idem)) headers.set("Idempotency-Key", idem);
  if (isIntentWrite(route.segments, route.method)) {
    // Concurrency and audit headers: only on intent writes, only validated
    // values. No other client-supplied X-Radius-* header is ever forwarded.
    const ifMatch = incoming.get("if-match");
    if (ifMatch && IF_MATCH_PATTERN.test(ifMatch)) headers.set("If-Match", ifMatch);
    const actor = incoming.get("x-radius-actor");
    if (actor && ACTOR_PATTERN.test(actor)) headers.set("X-Radius-Actor", actor);
  }
  const ct = (incoming.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (FORWARDED_CONTENT_TYPES.includes(ct)) headers.set("Content-Type", ct);
  return headers;
}
