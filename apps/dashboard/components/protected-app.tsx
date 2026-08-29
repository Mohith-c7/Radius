"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AuthProvider, useAuth } from "./auth-provider";

function Gate({ children }: { children: React.ReactNode }) { const { status } = useAuth(); const router = useRouter(); useEffect(() => { if (status === "unauthenticated") router.replace("/login"); }, [router, status]); if (status !== "authenticated") return <div className="auth-loading" role="status">Checking your Radius session…</div>; return <>{children}</>; }
const publicPaths = ["/login", "/signup", "/forgot-password", "/reset-password", "/verify-email"];
export function ProtectedApp({ children }: { children: React.ReactNode }) { const pathname = usePathname(); return <AuthProvider>{publicPaths.includes(pathname) ? children : <Gate>{children}</Gate>}</AuthProvider>; }
