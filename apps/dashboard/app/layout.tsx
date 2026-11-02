import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";
import { ProtectedApp } from "../components/protected-app";

export const metadata: Metadata = { title: "Radius | Verification intelligence", description: "The confidence layer for modern software development." };

// Reading request headers opts every page into dynamic rendering, which is
// required for the per-request CSP nonce set in middleware.ts to reach the
// scripts Next.js injects (statically prerendered HTML cannot carry a nonce).
export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  await headers();
  return <html lang="en"><body><ProtectedApp>{children}</ProtectedApp></body></html>;
}
