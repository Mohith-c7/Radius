"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

type CoverageSummary = { coverage_percent: number | null; available: boolean };

export function CoverageHealth() {
  const params = useParams<{ analysisId: string }>();
  const [coverage, setCoverage] = useState<CoverageSummary | null>(null);
  useEffect(() => {
    if (!params.analysisId) return;
    fetch(`/api/v1/coverage/analysis/${params.analysisId}`)
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => setCoverage(payload?.data ?? null))
      .catch(() => setCoverage(null));
  }, [params.analysisId]);
  return <div><span>Affected-path coverage</span><strong>{coverage?.available ? `${coverage.coverage_percent}%` : "Unavailable"}</strong></div>;
}
