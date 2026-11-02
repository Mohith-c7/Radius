import { NextRequest, NextResponse } from "next/server";

const publicPaths = ["/login", "/signup", "/forgot-password", "/reset-password", "/verify-email"];
export function middleware(request: NextRequest) {
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
    return NextResponse.next();
  }
  if (!hasSession && !isPublic) return NextResponse.redirect(new URL("/login", request.url));
  if (hasSession && (pathname === "/login" || pathname === "/signup")) return NextResponse.redirect(new URL("/", request.url));
  return NextResponse.next();
}
export const config = { matcher: ["/((?!_next|favicon.ico).*)"] };
