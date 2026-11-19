// Same-origin API proxy for split deployments (dashboard and API on different sites).
//
// The session cookie is set by the API and is host-only with SameSite=Lax. When the
// dashboard (for example *.vercel.app) and the API (for example *.onrender.com) are on
// different registrable domains, the browser never sends that cookie to the dashboard,
// so every page redirects to /login. With RADIUS_API_PUBLIC_UPSTREAM set, the dashboard
// forwards /api/v1/* to the API, so the browser only ever talks to the dashboard origin.
// Point NEXT_PUBLIC_API_URL and NEXT_PUBLIC_RADIUS_API_BASE_URL at the dashboard origin.

/**
 * @param {Record<string, string | undefined>} env
 * @returns {{ source: string, destination: string }[]}
 */
export function apiRewritesFrom(env) {
  const raw = (env.RADIUS_API_PUBLIC_UPSTREAM ?? "").trim();
  if (!raw) return [];
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`RADIUS_API_PUBLIC_UPSTREAM is not a URL: ${raw}`);
  }
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && local)) {
    throw new Error("RADIUS_API_PUBLIC_UPSTREAM must use https (http only for localhost)");
  }
  if (url.pathname !== "/" || url.search || url.hash) {
    throw new Error("RADIUS_API_PUBLIC_UPSTREAM must be an origin, e.g. https://api.example.com");
  }
  return [{ source: "/api/v1/:path*", destination: `${url.origin}/api/v1/:path*` }];
}
