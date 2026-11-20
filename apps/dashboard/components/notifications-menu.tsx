"use client";

import Link from "next/link";
import { Bell } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { listAnalyses } from "../lib/api";
import { recentNotifications, type AnalysisNotification } from "../lib/dashboard-model";

type Load = "idle" | "loading" | "error" | AnalysisNotification[];

function when(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

/** Header bell: the five newest finished analyses, fetched when first opened. */
export function NotificationsMenu() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Load>("idle");
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && (items === "idle" || items === "error")) {
      setItems("loading");
      listAnalyses({ limit: 50 })
        .then((analyses) => setItems(recentNotifications(analyses)))
        .catch(() => setItems("error"));
    }
  }

  return (
    <div
      ref={root}
      style={{ position: "relative" }}
      onBlur={(event) => {
        if (open && !root.current?.contains(event.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <button
        ref={button}
        type="button"
        className="icon-button"
        aria-label="Notifications"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={toggle}
      >
        <Bell size={19} />
      </button>
      {open && (
        <div
          id={panelId}
          role="region"
          aria-label="Recent analyses"
          className="card"
          style={{ position: "absolute", right: 0, top: "calc(100% + 8px)", width: 320, zIndex: 50, padding: 14 }}
        >
          <strong style={{ display: "block", marginBottom: 8 }}>Recent analyses</strong>
          {items === "loading" || items === "idle" ? (
            <p className="muted">Loading…</p>
          ) : items === "error" ? (
            <p className="muted">Could not load recent analyses.</p>
          ) : items.length === 0 ? (
            <p className="muted">All caught up.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}>
              {items.map((item) => (
                <li key={item.id}>
                  <Link href={`/analyses/${item.id}`} className="text-link" onClick={() => setOpen(false)}>
                    {item.failed ? "Analysis failed" : "Analysis completed"} · {item.commit}
                  </Link>
                  <div className="subtext">{when(item.at)}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
