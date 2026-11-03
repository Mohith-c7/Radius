"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body>
        <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif", background: "#F8FAF8", padding: "20px" }}>
          <div style={{ background: "#FFF", border: "1px solid #E7ECE8", borderRadius: "12px", padding: "32px", maxWidth: "440px", width: "100%" }}>
            <h2 style={{ fontSize: "20px", fontWeight: "800", color: "#17211E", margin: "0 0 8px" }}>Application Error</h2>
            <p style={{ fontSize: "13px", color: "#70807A", margin: "0 0 20px" }}>{error.message || "Something went wrong."}</p>
            <button onClick={() => reset()} style={{ background: "#19815C", color: "#FFF", border: "0", borderRadius: "8px", padding: "10px 16px", fontWeight: "700", cursor: "pointer" }}>
              Reload page
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
