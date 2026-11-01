"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { authRequest, type AuthUser } from "../lib/auth";

type AuthState = { status: "loading" | "authenticated" | "unauthenticated"; user: AuthUser | null; refresh: () => Promise<void>; signOut: () => Promise<void> };
const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthState["status"]>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const refresh = useCallback(async () => {
    try { setUser(await authRequest<AuthUser>("/auth/me")); setStatus("authenticated"); }
    catch { setUser(null); setStatus("unauthenticated"); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const signOut = useCallback(async () => { await authRequest<void>("/auth/logout", { method: "POST" }); setUser(null); setStatus("unauthenticated"); }, []);
  return <AuthContext.Provider value={{ status, user, refresh, signOut }}>{children}</AuthContext.Provider>;
}

export function useAuth() { const context = useContext(AuthContext); if (!context) throw new Error("useAuth must be used within AuthProvider"); return context; }
