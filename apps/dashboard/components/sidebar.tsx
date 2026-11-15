"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  BarChart3,
  Boxes,
  CircleHelp,
  FolderGit2,
  GitCompareArrows,
  GitPullRequest,
  LogOut,
  Search,
  Settings,
  Users,
  X,
} from "lucide-react";
import { useAuth } from "./auth-provider";

const verificationNav = [
  { href: "/", label: "Overview", icon: BarChart3 },
  { href: "/repositories", label: "Repositories", icon: FolderGit2 },
  { href: "/pull-requests", label: "Pull requests", icon: GitPullRequest },
  { href: "/analyses", label: "Analyses", icon: Activity },
];

const insightsNav = [
  { href: "/graph", label: "Dependency graph", icon: Boxes },
  { href: "/compare", label: "Compare analyses", icon: GitCompareArrows },
  { href: "/search", label: "Search", icon: Search },
];

export function Sidebar({
  isOpen = false,
  onClose,
}: {
  isOpen?: boolean;
  onClose?: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { signOut, user } = useAuth();
  const isActive = (href: string) => (href === "/" ? pathname === href : pathname.startsWith(href));

  return (
    <>
      {isOpen && <div className="mobile-backdrop" onClick={onClose} aria-hidden="true" />}
      <aside className={`sidebar${isOpen ? " open" : ""}`}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Link className="brand" href="/" onClick={onClose}>
            <span className="brand-mark">R</span>
            <span>radius</span>
          </Link>
          {isOpen && (
            <button
              onClick={onClose}
              style={{
                background: "none",
                border: 0,
                color: "var(--sidebar-text)",
                cursor: "pointer",
                padding: "8px",
                marginRight: "4px",
                marginTop: "-38px",
              }}
              aria-label="Close navigation"
            >
              <X size={18} />
            </button>
          )}
        </div>

        <nav>
          <div className="nav-group-label">Verification</div>
          {verificationNav.map(({ href, label, icon: Icon }) => (
            <Link
              className={`nav-link${isActive(href) ? " active" : ""}`}
              href={href}
              key={href}
              onClick={onClose}
            >
              <Icon size={17} />
              <span>{label}</span>
            </Link>
          ))}

          <div className="nav-group-label" style={{ marginTop: "12px" }}>Insights</div>
          {insightsNav.map(({ href, label, icon: Icon }) => (
            <Link
              className={`nav-link${isActive(href) ? " active" : ""}`}
              href={href}
              key={href}
              onClick={onClose}
            >
              <Icon size={17} />
              <span>{label}</span>
            </Link>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <Link
            className={`nav-link${isActive("/settings") ? " active" : ""}`}
            href="/settings"
            onClick={onClose}
          >
            <Settings size={16} />
            <span>Settings</span>
          </Link>
          <Link
            className={`nav-link${isActive("/organization") ? " active" : ""}`}
            href="/organization"
            onClick={onClose}
          >
            <Users size={16} />
            <span>Organization</span>
          </Link>
          <Link
            className={`nav-link${isActive("/help") ? " active" : ""}`}
            href="/help"
            onClick={onClose}
          >
            <CircleHelp size={16} />
            <span>Help & docs</span>
          </Link>

          <Link
            className={`profile-card${isActive("/profile") ? " active" : ""}`}
            href="/profile"
            onClick={onClose}
          >
            <span className="avatar-sm">
              {user?.name
                ?.split(" ")
                .map((part) => part[0])
                .slice(0, 2)
                .join("") ?? "R"}
            </span>
            <div style={{ minWidth: 0, overflow: "hidden" }}>
              <strong style={{ textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                {user?.name ?? "Radius User"}
              </strong>
              <small>{user?.role ?? "Developer"}</small>
            </div>
          </Link>

          <button
            className="logout-btn"
            onClick={async () => {
              if (onClose) onClose();
              await signOut();
              router.replace("/login");
            }}
          >
            <LogOut size={15} />
            <span>Log out</span>
          </button>
        </div>
      </aside>
    </>
  );
}
