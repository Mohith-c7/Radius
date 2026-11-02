// Security header policy for the dashboard (PRD-11). Plain ESM so both
// next.config.mjs and middleware.ts can import it; pure functions, unit tested.

/** Origin of the Radius API the browser talks to directly (auth cookies). */
export function apiOriginFrom(value) {
  try {
    return new URL(value || "http://localhost:8000").origin;
  } catch {
    return "";
  }
}

/**
 * Content-Security-Policy for HTML responses.
 *
 * Scripts: nonce + 'strict-dynamic' (no 'unsafe-inline'); Next.js forwards the
 * nonce to its own scripts when the request carries this policy.
 * Styles: 'unsafe-inline' is required because React renders style="" attributes
 * (documented residual risk; styles cannot execute script). Google Fonts is
 * allowed only because globals.css imports it (follow-up: self-host).
 */
export function buildCsp({ nonce, isDev = false, apiOrigin = "", upgradeInsecure = false }) {
  const connect = ["'self'", apiOrigin].filter(Boolean);
  if (isDev) connect.push("ws:", "wss:");
  const directives = [
    ["default-src", "'self'"],
    [
      "script-src",
      "'self'",
      `'nonce-${nonce}'`,
      "'strict-dynamic'",
      ...(isDev ? ["'unsafe-eval'"] : []),
    ],
    ["style-src", "'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
    ["font-src", "'self'", "https://fonts.gstatic.com", "data:"],
    ["img-src", "'self'", "data:", "blob:"],
    ["connect-src", ...connect],
    ["object-src", "'none'"],
    ["base-uri", "'self'"],
    ["form-action", "'self'"],
    ["frame-ancestors", "'none'"],
  ];
  if (upgradeInsecure) directives.push(["upgrade-insecure-requests"]);
  return directives.map((parts) => parts.join(" ")).join("; ");
}

/** Headers that do not vary per request; applied to every route incl. assets. */
export function staticSecurityHeaders({ hstsEnabled = false } = {}) {
  const headers = [
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    {
      key: "Permissions-Policy",
      value:
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()",
    },
    { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
    { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
  ];
  if (hstsEnabled) {
    headers.push({
      key: "Strict-Transport-Security",
      value: "max-age=31536000; includeSubDomains",
    });
  }
  return headers;
}

/** True when RADIUS_HSTS_ENABLED is set to a truthy value. */
export function hstsEnabledFrom(env) {
  return ["1", "true", "yes", "on"].includes(String(env.RADIUS_HSTS_ENABLED ?? "").toLowerCase());
}
