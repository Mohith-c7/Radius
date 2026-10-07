import type { Metadata } from "next";
import "./globals.css";
import { ProtectedApp } from "../components/protected-app";

export const metadata: Metadata = { title: "Radius | Verification intelligence", description: "The confidence layer for modern software development." };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body><ProtectedApp>{children}</ProtectedApp></body></html>; }
