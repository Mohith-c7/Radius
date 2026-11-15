"use client";

import { useEffect, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  Activity,
  Boxes,
  FolderGit2,
  GitCompareArrows,
  GitPullRequest,
  Search,
  Settings,
  X,
} from "lucide-react";
import { listRepositories, listAnalyses, Repository, Analysis } from "../lib/api";

export function CommandPalette({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);

  useEffect(() => {
    if (!isOpen) return;
    setQuery("");
    Promise.allSettled([listRepositories(), listAnalyses()]).then(([repoRes, analysisRes]) => {
      if (repoRes.status === "fulfilled") setRepositories(repoRes.value);
      if (analysisRes.status === "fulfilled") setAnalyses(analysisRes.value);
    });
  }, [isOpen]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (isOpen) onClose();
        else onClose(); // parent handles toggle
      } else if (e.key === "Escape" && isOpen) {
        onClose();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen, onClose]);

  const navItems = [
    { label: "Overview", href: "/", icon: Activity },
    { label: "Repositories", href: "/repositories", icon: FolderGit2 },
    { label: "Pull requests", href: "/pull-requests", icon: GitPullRequest },
    { label: "Analyses", href: "/analyses", icon: Activity },
    { label: "Dependency graph", href: "/graph", icon: Boxes },
    { label: "Compare analyses", href: "/compare", icon: GitCompareArrows },
    { label: "Settings", href: "/settings", icon: Settings },
  ];

  const filteredNav = useMemo(() => {
    if (!query.trim()) return navItems;
    const q = query.toLowerCase();
    return navItems.filter((i) => i.label.toLowerCase().includes(q));
  }, [query]);

  const filteredRepos = useMemo(() => {
    if (!query.trim()) return repositories.slice(0, 4);
    const q = query.toLowerCase();
    return repositories.filter(
      (r) =>
        r.full_name.toLowerCase().includes(q) ||
        r.name.toLowerCase().includes(q) ||
        r.owner.toLowerCase().includes(q)
    );
  }, [repositories, query]);

  const filteredAnalyses = useMemo(() => {
    if (!query.trim()) return analyses.slice(0, 4);
    const q = query.toLowerCase();
    return analyses.filter(
      (a) =>
        (a.id && a.id.toLowerCase().includes(q)) ||
        (a.commit_sha && a.commit_sha.toLowerCase().includes(q)) ||
        (a.status && a.status.toLowerCase().includes(q))
    );
  }, [analyses, query]);

  if (!isOpen) return null;

  function selectItem(href: string) {
    onClose();
    router.push(href);
  }

  return (
    <div className="cmd-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label="Command search">
      <div className="cmd-modal" onClick={(e) => e.stopPropagation()}>
        <div className="cmd-search-row">
          <Search size={18} />
          <input
            className="cmd-search-input"
            placeholder="Search repositories, pull requests, analyses, or pages..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
          <button
            onClick={onClose}
            style={{ background: "none", border: 0, color: "var(--muted)", cursor: "pointer", padding: "2px" }}
            aria-label="Close search"
          >
            <X size={16} />
          </button>
        </div>

        <div className="cmd-results">
          {filteredNav.length > 0 && (
            <div>
              <div className="cmd-group-title">Navigation</div>
              {filteredNav.map((item) => {
                const Icon = item.icon;
                return (
                  <div
                    key={item.href}
                    className="cmd-item"
                    onClick={() => selectItem(item.href)}
                  >
                    <Icon size={16} style={{ color: "var(--green)" }} />
                    <span>{item.label}</span>
                  </div>
                );
              })}
            </div>
          )}

          {filteredRepos.length > 0 && (
            <div style={{ marginTop: "8px" }}>
              <div className="cmd-group-title">Repositories</div>
              {filteredRepos.map((repo) => (
                <div
                  key={repo.id ?? repo.full_name}
                  className="cmd-item"
                  onClick={() => selectItem(`/repositories/${repo.id}`)}
                >
                  <FolderGit2 size={16} style={{ color: "var(--green-accent)" }} />
                  <span>{repo.full_name}</span>
                  <small>{repo.default_branch}</small>
                </div>
              ))}
            </div>
          )}

          {filteredAnalyses.length > 0 && (
            <div style={{ marginTop: "8px" }}>
              <div className="cmd-group-title">Recent Analyses</div>
              {filteredAnalyses.map((analysis) => (
                <div
                  key={analysis.id}
                  className="cmd-item"
                  onClick={() => selectItem(`/analyses/${analysis.id}`)}
                >
                  <Activity size={16} style={{ color: "var(--green)" }} />
                  <span>
                    Analysis {analysis.id?.slice(0, 8)}… ({analysis.status})
                  </span>
                  <small style={{ fontFamily: "var(--font-mono)" }}>
                    {analysis.commit_sha?.slice(0, 7)}
                  </small>
                </div>
              ))}
            </div>
          )}

          {filteredNav.length === 0 && filteredRepos.length === 0 && filteredAnalyses.length === 0 && (
            <div style={{ padding: "24px 16px", textAlign: "center", color: "var(--muted)", fontSize: "13px" }}>
              No matching resources found for &ldquo;{query}&rdquo;.
            </div>
          )}
        </div>

        <div className="cmd-footer">
          <span>Navigate with mouse or click item</span>
          <span><kbd style={{ fontFamily: "var(--font-mono)" }}>ESC</kbd> to close</span>
        </div>
      </div>
    </div>
  );
}
