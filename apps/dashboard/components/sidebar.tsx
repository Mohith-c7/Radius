import Link from "next/link";
import { BarChart3, Boxes, CircleHelp, FolderGit2, GitCompareArrows, GitPullRequest, Search, Settings, Users } from "lucide-react";

const navigation = [
  { href: "/", label: "Overview", icon: BarChart3 },
  { href: "/repositories", label: "Repositories", icon: FolderGit2 },
  { href: "/analyses", label: "Analyses", icon: GitPullRequest },
  { href: "/graph", label: "Dependency graph", icon: Boxes },
  { href: "/compare", label: "Compare analyses", icon: GitCompareArrows },
  { href: "/search", label: "Search", icon: Search }
];

export function Sidebar() {
  return <aside className="sidebar">
    <Link className="brand" href="/"><span className="brand-mark">R</span><span>radius</span></Link>
    <nav>{navigation.map(({ href, label, icon: Icon }) => <Link className="nav-link" href={href} key={href}><Icon size={18}/>{label}</Link>)}</nav>
    <div className="sidebar-bottom">
      <Link className="nav-link" href="/settings"><Settings size={18}/>Settings</Link>
      <Link className="nav-link" href="/organization"><Users size={18}/>Organization</Link>
      <button className="profile"><span className="avatar">SM</span><span><strong>Sanjith M.</strong><small>Developer</small></span></button>
      <a className="help" href="#support"><CircleHelp size={17}/>Help & support</a>
    </div>
  </aside>;
}
