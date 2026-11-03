import { NextRequest, NextResponse } from "next/server";
import { loadProxyConfig } from "./lib/proxy";
import { SESSION_COOKIE, validateSession } from "./lib/session";
import { apiOriginFrom, buildCsp, hstsEnabledFrom } from "./lib/security-headers.mjs";

const publicPaths = ["/login", "/signup", "/forgot-password", "/reset-password", "/verify-email"];
/** Per-request CSP nonce; Next.js applies it to its own scripts. */
function newNonce(): string {
  return btoa(crypto.randomUUID());
}

export async function middleware(request: NextRequest) {
  const nonce = newNonce();
  const csp = buildCsp({
    nonce,
    isDev: process.env.NODE_ENV === "development",
    apiOrigin: apiOriginFrom(process.env.NEXT_PUBLIC_RADIUS_API_BASE_URL),
    upgradeInsecure: hstsEnabledFrom(process.env),
  });
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const response = await handle(request, requestHeaders);
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

async function handle(request: NextRequest, requestHeaders: Headers): Promise<NextResponse> {
  const { pathname } = request.nextUrl;
  const cookie = request.cookies.get(SESSION_COOKIE)?.value;
  const isDev = process.env.NODE_ENV === "development";
  // C-01: a cookie only counts when the API confirms it (cached for seconds,
  // fail closed on any error). Presence of a cookie is never authentication.
  // Development (`next dev`) keeps the old no-auth behaviour for local work.
  let hasSession = Boolean(cookie);
  if (cookie && !isDev) {
    const check = await validateSession(cookie, { apiBaseUrl: loadProxyConfig().apiBaseUrl });
    hasSession = check.ok;
    if (!check.ok && check.reason === "unavailable" && pathname.startsWith("/api/radius/")) {
      return NextResponse.json(
        { success: false, data: null, error: { code: "AUTH_UNAVAILABLE", message: "Sign-in could not be verified. Try again." } },
        { status: 503 },
      );
    }
  }
  if (pathname.startsWith("/api/radius/") && !hasSession && !isDev) {
    return NextResponse.json(
      { success: false, data: null, error: { code: "UNAUTHENTICATED", message: "Sign in required." } },
      { status: 401 },
    );
  }
  const isPublic = publicPaths.some((path) => pathname === path);
  if (process.env.NODE_ENV === "development") {
    if (hasSession && (pathname === "/login" || pathname === "/signup")) {
      return NextResponse.redirect(new URL("/", request.url));
    }
    return NextResponse.next({ request: { headers: requestHeaders } });
  }
  if (!hasSession && !isPublic) return NextResponse.redirect(new URL("/login", request.url));
  if (hasSession && (pathname === "/login" || pathname === "/signup")) return NextResponse.redirect(new URL("/", request.url));
  return NextResponse.next({ request: { headers: requestHeaders } });
}
export const config = { matcher: ["/((?!_next|favicon.ico).*)"] };
