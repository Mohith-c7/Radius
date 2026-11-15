import Link from "next/link";
import {
  AlertCircle,
  ArrowUpRight,
  CheckCircle2,
  ChevronRight,
  Clock3,
  XCircle,
} from "lucide-react";

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

export function PageHeading({
  eyebrow,
  breadcrumbs,
  title,
  description,
  action,
  status,
}: {
  eyebrow?: string; // Kept for backwards compatibility, not rendered as kicker per Impeccable craft rules
  breadcrumbs?: BreadcrumbItem[];
  title: string;
  description?: string;
  action?: React.ReactNode;
  status?: string;
}) {
  return (
    <div className="page-heading">
      <div>
        {breadcrumbs && breadcrumbs.length > 0 && (
          <nav className="breadcrumbs" aria-label="Breadcrumbs">
            {breadcrumbs.map((crumb, idx) => (
              <span key={idx} style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                {crumb.href ? (
                  <Link href={crumb.href}>{crumb.label}</Link>
                ) : (
                  <span style={{ color: "var(--ink)", fontWeight: 600 }}>{crumb.label}</span>
                )}
                {idx < breadcrumbs.length - 1 && (
                  <ChevronRight size={13} className="breadcrumbs-separator" />
                )}
              </span>
            ))}
          </nav>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
          <h1>{title}</h1>
          {status && <Status status={status} />}
        </div>
        {description && <p className="page-heading-description">{description}</p>}
      </div>
      {action && <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>{action}</div>}
    </div>
  );
}

export function Status({ status }: { status: string }) {
  const normalized = (status || "").toLowerCase().replaceAll("_", " ");

  const isPositive = [
    "verified",
    "healthy",
    "connected",
    "completed",
    "passed",
    "low",
    "stable",
  ].includes(normalized);

  const isError = ["failed", "cancelled", "error"].includes(normalized);

  const isNeutral = [
    "running",
    "pending",
    "synchronizing",
    "open",
    "medium",
    "insufficient_data",
  ].includes(normalized);

  const isWarning = [
    "warning",
    "attention",
    "high",
    "potentially flaky",
    "not verified",
  ].includes(normalized) || (!isPositive && !isError && !isNeutral);

  let icon = <Clock3 size={13} />;
  let className = "neutral";

  if (isPositive) {
    icon = <CheckCircle2 size={13} />;
    className = "positive";
  } else if (isError) {
    icon = <XCircle size={13} />;
    className = "error";
  } else if (isWarning) {
    icon = <AlertCircle size={13} />;
    className = "warning";
  }

  return (
    <span className={`status ${className}`}>
      {icon}
      <span>{normalized}</span>
    </span>
  );
}

export function ConfidenceRing({
  score,
  size = "large",
}: {
  score: number;
  size?: "large" | "small";
}) {
  const safeScore = Math.max(0, Math.min(100, Math.round(score || 0)));
  return (
    <div
      className={`confidence-ring ${size}`}
      style={{ "--score": `${safeScore * 3.6}deg` } as React.CSSProperties}
      role="meter"
      aria-valuenow={safeScore}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`Confidence score: ${safeScore} out of 100`}
    >
      <div>
        <strong>{safeScore > 0 ? safeScore : "-"}</strong>
        {safeScore > 0 && size !== "small" && <small>/100</small>}
      </div>
    </div>
  );
}

export function MetricTile({
  label,
  value,
  context,
  icon,
}: {
  label: string;
  value: React.ReactNode;
  context?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="metric-tile">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <p className="metric-tile-label">{label}</p>
        {icon && <span style={{ color: "var(--muted)" }}>{icon}</span>}
      </div>
      <div className="metric-tile-value">{value}</div>
      {context && <p className="metric-tile-context">{context}</p>}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  detail,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  detail: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-icon-wrap">{icon}</div>}
      <h3>{title}</h3>
      <p>{detail}</p>
      {action}
    </div>
  );
}

export function Skeleton({
  height = "20px",
  width = "100%",
  borderRadius = "6px",
}: {
  height?: string;
  width?: string;
  borderRadius?: string;
}) {
  return (
    <div
      className="skeleton-box"
      style={{ height, width, borderRadius, display: "inline-block" }}
    />
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
      <ArrowUpRight size={14} />
    </Link>
  );
}
