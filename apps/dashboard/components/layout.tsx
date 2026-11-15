"use client";

import { useState } from "react";
import { Menu, Search } from "lucide-react";
import { Sidebar } from "./sidebar";
import { CommandPalette } from "./command-palette";

export function AppLayout({ children }: { children: React.ReactNode }) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);

  return (
    <div className="app-shell">
      <Sidebar isOpen={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)} />
      <main className="main">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="mobile-menu-btn"
              onClick={() => setMobileMenuOpen(true)}
              aria-label="Open navigation menu"
            >
              <Menu size={18} />
            </button>
            <button
              className="search-trigger"
              onClick={() => setCmdOpen(true)}
              type="button"
              aria-label="Search resources"
            >
              <Search size={15} />
              <span>Search repositories, PRs, and analyses…</span>
              <kbd className="kbd-shortcut">⌘K</kbd>
            </button>
          </div>
          <div className="topbar-right">
            <a
              href="https://github.com/Mohith-c7/Radius"
              target="_blank"
              rel="noreferrer"
              className="topbar-link"
            >
              GitHub Docs
            </a>
          </div>
        </header>
        {children}
      </main>
      <CommandPalette isOpen={cmdOpen} onClose={() => setCmdOpen(false)} />
    </div>
  );
}
