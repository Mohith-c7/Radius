import Link from "next/link";
import { ArrowUpRight, CheckCircle2, Clock3, AlertCircle } from "lucide-react";
import type { AnalysisStatus } from "../lib/data";

export function PageHeading({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description: string; action?: React.ReactNode }) {
  return <div className="page-heading"><div><p className="eyebrow">{eyebrow ?? "Workspace"}</p><h1>{title}</h1><p className="muted">{description}</p></div>{action}</div>;
}

export function Status({ status }: { status: AnalysisStatus | "Healthy" | "Attention" }) {
  const icon = status === "Verified" || status === "Healthy" ? <CheckCircle2 size={14}/> : status === "Running" ? <Clock3 size={14}/> : <AlertCircle size={14}/>;
  const className = status === "Verified" || status === "Healthy" ? "positive" : status === "Running" ? "neutral" : "warning";
  return <span className={`status ${className}`}>{icon}{status}</span>;
}

export function ConfidenceRing({ score, size = "large" }: { score: number; size?: "large" | "small" }) {
  return <div className={`confidence-ring ${size}`} style={{ "--score": `${score * 3.6}deg` } as React.CSSProperties}><div><strong>{score || "—"}</strong>{score > 0 && <small>/100</small>}</div></div>;
}

export function OpenLink({ href, children }: { href: string; children: React.ReactNode }) { return <Link href={href} className="text-link">{children}<ArrowUpRight size={15}/></Link>; }
