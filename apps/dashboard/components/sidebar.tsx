"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRouter } from "next/navigation";
import { Activity, BarChart3, Boxes, CircleHelp, FolderGit2, GitCompareArrows, GitPullRequest, LogOut, Search, Settings, Users } from "lucide-react";
import { useAuth } from "./auth-provider";

const navigation = [
  { href: "/", label: "Overview", icon: BarChart3 },
  { href: "/repositories", label: "Repositories", icon: FolderGit2 },
  { href: "/pull-requests", label: "Pull requests", icon: GitPullRequest },
  { href: "/analyses", label: "Analyses", icon: Activity },
  { href: "/graph", label: "Dependency graph", icon: Boxes },
  { href: "/compare", label: "Compare analyses", icon: GitCompareArrows },
  { href: "/search", label: "Search", icon: Search }
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { signOut, user } = useAuth();
  const isActive = (href: string) => href === "/" ? pathname === href : pathname.startsWith(href);

  return <aside className="sidebar">
    <Link className="brand" href="/"><span className="brand-mark">R</span><span>radius</span></Link>
    <nav>{navigation.map(({ href, label, icon: Icon }) => <Link className={`nav-link${isActive(href) ? " active" : ""}`} href={href} key={href}><Icon size={18}/>{label}</Link>)}</nav>
    <div className="sidebar-bottom">
      <Link className={`nav-link${isActive("/settings") ? " active" : ""}`} href="/settings"><Settings size={18}/>Settings</Link>
      <Link className={`nav-link${isActive("/organization") ? " active" : ""}`} href="/organization"><Users size={18}/>Organization</Link>
      <Link className={`profile${isActive("/profile") ? " active" : ""}`} href="/profile"><span className="avatar">{user?.name.split(" ").map((part) => part[0]).slice(0, 2).join("") ?? "R"}</span><span><strong>{user?.name ?? "Radius user"}</strong><small>{user?.role ?? "Developer"}</small></span></Link>
      <Link className={`help${isActive("/help") ? " active" : ""}`} href="/help"><CircleHelp size={17}/>Help & support</Link>
      <button className="logout" onClick={async () => { await signOut(); router.replace("/login"); }}><LogOut size={17}/>Log out</button>
    </div>
  </aside>;
}
