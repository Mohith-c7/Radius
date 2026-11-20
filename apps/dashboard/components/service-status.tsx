"use client";

import { useEffect, useState } from "react";

import { getReadiness } from "../lib/api";
import { describeReadiness } from "../lib/dashboard-model";

/** Live status line from GET /ready (database and job queue), not a hard-coded claim. */
export function ServiceStatus() {
  const [result, setResult] = useState<"loading" | "error" | { status: number }>("loading");
  useEffect(() => {
    let active = true;
    getReadiness()
      .then((value) => active && setResult(value))
      .catch(() => active && setResult("error"));
    return () => {
      active = false;
    };
  }, []);
  const { tone, text } = describeReadiness(result);
  return (
    <p className="muted" role="status" data-tone={tone}>
      {text}
    </p>
  );
}
