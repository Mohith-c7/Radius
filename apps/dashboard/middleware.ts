import { NextRequest, NextResponse } from "next/server";
import { apiOriginFrom, buildCsp, hstsEnabledFrom } from "./lib/security-headers.mjs";

const publicPaths = ["/login", "/signup", "/forgot-password", "/reset-password", "/verify-email"];
/** Per-request CSP nonce; Next.js applies it to its own scripts. */
function newNonce(): string {
  return btoa(crypto.randomUUID());
}

export function middleware(request: NextRequest) {
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
  const response = handle(request, requestHeaders);
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

function handle(request: NextRequest, requestHeaders: Headers): NextResponse {
  const { pathname } = request.nextUrl;
  const hasSession = Boolean(request.cookies.get("radius_session")?.value);
  if (pathname.startsWith("/api/radius/") && !hasSession && process.env.NODE_ENV !== "development") {
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
