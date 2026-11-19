import { apiRewritesFrom } from "./lib/api-rewrites.mjs";
import { hstsEnabledFrom, staticSecurityHeaders } from "./lib/security-headers.mjs";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Split deployments: forward /api/v1/* to the API so the session cookie stays
  // first-party (see lib/api-rewrites.mjs). No-op unless RADIUS_API_PUBLIC_UPSTREAM is set.
  async rewrites() {
    return apiRewritesFrom(process.env);
  },
  async headers() {
    // Per-request CSP (with nonce) is set in middleware.ts; these static headers
    // also cover assets the middleware matcher skips (/_next/*).
    return [
      {
        source: "/:path*",
        headers: staticSecurityHeaders({ hstsEnabled: hstsEnabledFrom(process.env) }),
      },
    ];
  },
};

export default nextConfig;
