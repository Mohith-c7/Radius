import { hstsEnabledFrom, staticSecurityHeaders } from "./lib/security-headers.mjs";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
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
