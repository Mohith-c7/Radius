"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

/** A short id with a button that copies the full value (for support and CI configuration). */
export function CopyId({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      {label} <code title={value}>{value.slice(0, 8)}</code>
      <button
        type="button"
        onClick={() => void copy()}
        aria-label={`Copy full ${label.toLowerCase()}`}
        title={copied ? "Copied" : `Copy full ${label.toLowerCase()}`}
        style={{ background: "transparent", border: "none", padding: 2, cursor: "pointer", color: "var(--muted)" }}
      >
        {copied ? <Check size={12} /> : <Copy size={12} />}
      </button>
    </span>
  );
}

/** A labelled copy button (Settings: CI values, a new API key token). */
export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="copy-button"
      disabled={!value}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        } catch {
          setCopied(false);
        }
      }}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
      {copied ? "Copied" : label}
    </button>
  );
}
