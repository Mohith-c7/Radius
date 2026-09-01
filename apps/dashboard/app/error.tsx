"use client";

import { useEffect } from "react";
import Link from "next/link";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("App boundary error:", error);
  }, [error]);

  return (
    <main className="auth-layout">
      <section className="auth-form-panel" style={{ width: "100%" }}>
        <div className="auth-card">
          <Link className="auth-brand" href="/">
            <span className="brand-mark">R</span>
            <span className="brand-text">radius</span>
          </Link>
          <header className="auth-header">
            <h1>Something went wrong</h1>
            <p>{error.message || "An unexpected error occurred. Please try again."}</p>
          </header>
          <div style={{ display: "flex", gap: "12px", marginTop: "20px" }}>
            <button className="auth-submit" onClick={() => reset()}>
              Try again
            </button>
            <Link className="auth-submit" href="/login" style={{ background: "#FFFFFF", color: "#17211E", border: "1px solid #E7ECE8", textDecoration: "none" }}>
              Back to Sign In
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}
