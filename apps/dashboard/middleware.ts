import { NextRequest, NextResponse } from "next/server";

const publicPaths = ["/login", "/signup", "/forgot-password", "/reset-password", "/verify-email"];
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = Boolean(request.cookies.get("radius_session")?.value);
  const isPublic = publicPaths.some((path) => pathname === path);
  if (!hasSession && !isPublic) return NextResponse.redirect(new URL("/login", request.url));
  if (hasSession && (pathname === "/login" || pathname === "/signup")) return NextResponse.redirect(new URL("/", request.url));
  return NextResponse.next();
}
export const config = { matcher: ["/((?!_next|favicon.ico).*)"] };
