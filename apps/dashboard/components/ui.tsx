import Link from "next/link";
import { scoreKindLabel } from "../lib/score-kind";
import { AlertCircle, ArrowUpRight, CheckCircle2, Clock3 } from "lucide-react";

export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow ?? "Workspace"}</p>
        <h1>{title}</h1>
        <p className="muted">{description}</p>
      </div>
      {action}
    </div>
  );
}

export function Status({ status }: { status: string }) {
  const normalized = status.toLowerCase().replaceAll("_", " ");
  const positive = ["verified", "healthy", "connected", "completed", "low"].includes(
    normalized,
  );
  const neutral = ["running", "pending", "synchronizing", "open", "medium"].includes(
    normalized,
  );
  const icon = positive ? (
    <CheckCircle2 size={14} />
  ) : neutral ? (
    <Clock3 size={14} />
  ) : (
    <AlertCircle size={14} />
  );
  const className = positive ? "positive" : neutral ? "neutral" : "warning";
  return (
    <span className={`status ${className}`}>
      {icon}
      {normalized}
    </span>
  );
}

export function ConfidenceRing({
  score,
  size = "large",
  scoreKind,
  muted = false,
}: {
  score: number;
  size?: "large" | "small";
  scoreKind?: string | null;
  /** Demoted (legacy v1) styling: grey, never green. */
  muted?: boolean;
}) {
  return (
    <div
      className={`confidence-ring ${size}${muted ? " muted" : ""}`}
      title={scoreKindLabel(scoreKind).tooltip}
      style={{ "--score": `${score * 3.6}deg` } as React.CSSProperties}
    >
      <div>
        <strong>{score || "-"}</strong>
        {score > 0 && <small>/100</small>}
      </div>
    </div>
  );
}

export function OpenLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <Link href={href} className="text-link">
      {children}
      <ArrowUpRight size={15} />
    </Link>
  );
}
